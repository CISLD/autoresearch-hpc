"""Delegate execution to Nextflow; keep only protocol checks and run receipts."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import shutil
import shlex
import sys
import tempfile
import time

import re

import freeze
import imports
import inputs
import lease
from locks import Held, acquire, owner, release
from project import config, guard

GPU_LABELS = ('gpu', 'process_gpu')
# Groovy, evaluated per task in the generated config: does this task want a GPU?
WANTS_GPU = ("((task.label ?: []).any { it in ['" + "', '".join(GPU_LABELS) + "'] } || task.accelerator)")


def literal(value):
    return json.dumps(str(value)).replace('$', '\\$')


def slurm_settings(site, gpu):
    """Generated config lines for Slurm. A GPU task goes to the GPU partition with a generic-resource
    request sized by its accelerator directive; the GPU type or a constraint keeps it off cards too
    small for it. Other tasks keep the ordinary partition."""
    lines = [f'process.{directive} = {literal(site[key])}'
             for key, directive in [('slurm_time', 'time'), ('slurm_mem', 'memory')] if site.get(key)]
    if site.get('slurm_cpus'):
        lines.append('process.cpus = ' + str(int(site['slurm_cpus'])))
    cluster_options = site.get('slurm_extra', '')
    if site.get('slurm_account'):
        cluster_options += ' --account=' + shlex.quote(site['slurm_account'])
    cluster_options = cluster_options.strip()
    partition = site.get('slurm_partition')
    if not gpu:
        if partition:
            lines.append(f'process.queue = {literal(partition)}')
        if cluster_options:
            lines.append('process.clusterOptions = ' + literal(cluster_options))
        return lines
    gpu_part = site.get('gpu_partition') or partition
    gres = 'gpu:' + (site['gpu_type'] + ':' if site.get('gpu_type') else '')
    extra = ((' --constraint=' + shlex.quote(site['gpu_constraint'])) if site.get('gpu_constraint') else '') \
        + ((' ' + site['gpu_extra']) if site.get('gpu_extra') else '')
    if gpu_part:
        lines.append(f"process.queue = {{ {WANTS_GPU} ? {literal(gpu_part)} : "
                     f"{literal(partition) if partition else 'null'} }}")
    lines.append(f"process.clusterOptions = {{ {literal(cluster_options)} + ({WANTS_GPU} ? "
                 f"' --gres={gres}' + (task.accelerator ? (task.accelerator.request ?: 1) : 1)"
                 f" + {literal(extra)} : '') }}")
    return lines


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def lint(workflow, root, site, parser):
    """`nextflow lint` with the pinned controller, so strict-syntax errors surface before a run exists."""
    prefix = site.get('nextflow_prefix')
    binary = Path(prefix or '') / 'bin/nextflow'
    if not prefix or not binary.is_file():
        parser.error('configure nextflow_prefix to lint with the pinned Nextflow (see arh doctor)')
    if workflow.suffix != '.nf':
        parser.error('only a .nf workflow can be linted')
    env = dict(os.environ, NXF_HOME=str(root / '.arh/nextflow'), NXF_ANSI_LOG='false',
               NXF_DISABLE_CHECK_LATEST='true', NXF_OFFLINE='true')
    env.pop('NXF_VER', None)
    with tempfile.TemporaryDirectory(prefix='arh-lint-') as scratch:   # lint writes .nextflow.log to its cwd
        return subprocess.run([str(binary), '-log', scratch + '/nextflow.log', 'lint', str(workflow)],
                              cwd=scratch, env=env).returncode


def detach(lock, logs, owner_dir, kind):
    """Start this submission again in its own session and return once it holds the launch lock.

    `arh submit` blocks until Nextflow exits and forwards a stop signal to it, so an agent harness
    that caps background tasks (Claude Code: 2 h) stopped long runs when the cap hit (2026-10-04).
    The child runs in a new session, so a signal to the caller's process group does not reach it."""
    log = logs / ('detached-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.log')
    argv = [a for a in sys.argv[1:] if a != '--detach']
    with open(log, 'w') as out:
        child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), *argv], stdin=subprocess.DEVNULL,
                                 stdout=out, stderr=subprocess.STDOUT, start_new_session=True,
                                 env=dict(os.environ, ARH_DETACHED='1'))
    deadline = time.time() + 600
    while time.time() < deadline and child.poll() is None:
        record = owner(lock)
        if record and record.get('pid') == child.pid:
            break
        time.sleep(0.5)
    if child.poll() is not None and child.returncode:
        print(log.read_text()[-3000:], file=sys.stderr)
        return child.returncode
    follow = (f'arh wait -n {owner_dir.name[9:]}' if kind == 'iteration' else 'arh status --running')
    print(log)
    print(f'arh: detached as pid {child.pid}; follow it with `{follow}` or `arh status --running`; '
          f'its output, and the attempt directory when it ends, are in {log}', file=sys.stderr)
    return 0


def notify(hook, record, attempt, name, owner, root):
    """Run the on_exit command once Nextflow has exited. A detached run that failed while its session
    was stopped at a usage limit stayed failed for hours with nobody told (field feedback #61, #63).
    The command gets the outcome in ARH_RUN_* variables; it cannot change the run or its receipt."""
    env = dict(os.environ, ARH_RUN_EXIT=str(record.get('exit_code')), ARH_RUN_NAME=name,
               ARH_RUN_ATTEMPT=str(attempt), ARH_RUN_OWNER=str(Path(owner).relative_to(root)),
               ARH_RUN_SIGNAL=record.get('signal') or '', ARH_ROOT=str(root))
    try:
        done = subprocess.run(shlex.split(hook), env=env, cwd=root, stdin=subprocess.DEVNULL,
                              capture_output=True, text=True, timeout=120)
    except (OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f'arh: on_exit command failed: {error}', file=sys.stderr)
        return dict(command=hook, exit_code=None, error=str(error)[:200])
    if done.returncode:
        print(f'arh: on_exit command exited {done.returncode}', file=sys.stderr)
    return dict(command=hook, exit_code=done.returncode)


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workflow', type=Path)
    parser.add_argument('-n', '--name')
    parser.add_argument('-w', '--wait', action='store_true', help='compatibility flag; Nextflow always owns the run until completion')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--params', type=Path, help='Nextflow JSON/YAML params file')
    parser.add_argument('-l', '--logdir', type=Path)
    parser.add_argument('--lint', action='store_true', help='check the workflow with the pinned Nextflow; nothing runs')
    parser.add_argument('--detach', action='store_true',
                        help='return once the run holds its launch lock; follow it with arh wait or arh status --running')
    parser.add_argument('--on-exit', metavar='CMD',
                        help="run CMD when Nextflow exits (as site.md's on_exit), e.g. to mail or notify a watcher")
    args = parser.parse_args()
    root, home = Path(os.environ['ARH_ROOT']), Path(os.environ['ARH_HOME'])
    site = config(root / '.arh/config/site.md')
    project = config(root / '.arh/config/project.md')
    immutable = project.get('immutable_inputs', '').split()
    workflow = args.workflow.resolve()
    # `arh doctor --smoke` runs the framework's own one-task workflow through the real executor and
    # container. It is fixed framework code, so it needs no plan; its evidence stays in .arh/smoke/.
    if workflow == (home / 'workflows/smoke.nf').resolve():
        iteration, kind, plan = root / '.arh/smoke', 'smoke', None
        iteration.mkdir(parents=True, exist_ok=True)
    else:
        if not workflow.is_file() or root not in workflow.parents:
            parser.error('workflow must be a local file inside the study')
        # The owner is the claimed iteration the workflow sits in, or a verification object: a
        # verification's computation gets the same pinned image and receipt as an iteration's.
        verify_base = (root / project.get('verification_dir', 'verification')).resolve()
        iteration = next((p for p in workflow.parents if (p / 'CLAIM.json').is_file()), None)
        kind = 'iteration'
        if iteration is None and verify_base in workflow.parents:
            candidate = verify_base / workflow.relative_to(verify_base).parts[0]
            if (candidate / 'PREDECLARATION.md').is_file():
                iteration, kind = candidate, 'verification'
        if iteration is None or root not in iteration.parents:
            parser.error('workflow must belong to a claimed iteration or a verification (arh verify new)')
        plan = iteration / ('README.md' if kind == 'iteration' else 'PREDECLARATION.md')
    if args.lint:
        return lint(workflow, root, site, parser)
    import_sha256 = {}
    if kind != 'smoke':
        predeclared = iteration / 'PREDECLARATION.sha256'
        if not predeclared.is_file() or predeclared.read_text().splitlines()[0] != sha(plan):
            parser.error(f'{kind} must have an unchanged frozen pre-declaration')
        import_sha256, problems = imports.check(root, iteration, plan)
        for problem in problems:
            if problem.startswith('warn:'):
                print('arh: ' + problem[5:], file=sys.stderr)
            else:
                parser.error(problem + '. A changed dependency is a new iteration.')
    # Scripts that were in scripts/ when the plan was frozen are pinned with it (frozen_scripts).
    pinned_changed = imports.pinned_changes(root, iteration) if kind != 'smoke' else []
    policy = project.get('frozen_scripts') or 'warn'
    if policy not in ('warn', 'refuse', 'off'):
        parser.error('frozen_scripts must be warn, refuse or off')
    if pinned_changed and policy == 'refuse':
        parser.error('scripts pinned with the frozen plan changed: ' + ', '.join(pinned_changed)
                     + '. A changed plan is a new iteration (frozen_scripts = refuse).')
    if pinned_changed and policy == 'warn':
        print('arh: scripts pinned with the frozen plan changed since the freeze: ' + ', '.join(pinned_changed)
              + '. Report it as a deviation; the run receipt records it.', file=sys.stderr)
    # A confirmation applies frozen decisions; one whose decisions changed under it is not that run.
    frozen_state, freeze_sha, changed = freeze.state(root, iteration)
    if frozen_state == 'changed':
        parser.error('files frozen in FREEZE.json changed since the freeze: ' + ', '.join(changed)
                     + '. A changed configuration is a new iteration.')
    sealed = freeze.sealed_inputs(root)
    # A valid freeze releases only the sealed groups it names; every other sealed path stays hidden.
    readable = freeze.unsealed(root, iteration) if sealed and kind != 'smoke' else []
    hidden = [p for p in sealed if p not in readable]
    unsealed = bool(readable)
    if hidden and kind != 'smoke':
        scripts_dir = iteration / 'scripts'
        texts = [workflow] + ([args.params.resolve()] if args.params else []) + (
            [p for p in sorted(scripts_dir.rglob('*')) if p.is_file()] if scripts_dir.is_dir() else [])
        named = freeze.references(root, texts, hidden)
        if named:
            parser.error('sealed input ' + named[0][1] + ' is named in ' + str(Path(named[0][0]).relative_to(root))
                         + ': only a run of an iteration whose valid freeze unseals its group may read it '
                         '(arh freeze -n N [--unseal GROUP] FILE...).')
    name = args.name or workflow.stem
    if not name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in name):
        parser.error('name must contain only letters, digits, underscores and hyphens')
    if workflow.suffix not in ('.nf', '.sh'):
        parser.error('supply a native .nf workflow or a migration .sh script')
    if args.resume and workflow.suffix == '.sh':
        parser.error('resume requires a native .nf workflow with declared inputs; shell adapter is never cached')
    image = site.get('runtime_image') or os.environ.get('ARH_RUNTIME_IMAGE')
    prefix = site.get('nextflow_prefix')
    if os.environ.get('APPTAINER_CONTAINER') or os.environ.get('SINGULARITY_CONTAINER'):
        parser.error('run the Nextflow controller on the host, outside Singularity')
    if not image or not prefix:
        parser.error('configure runtime_image and nextflow_prefix for the host micromamba driver')
    binary = Path(prefix) / 'bin/nextflow'
    if not binary.is_file():
        parser.error('versioned micromamba env/bin/nextflow is missing; host fallback is disabled')
    pin = json.loads((home / 'config/dependencies.json').read_text())['nextflow']
    version = site.get('nextflow_version') or pin['version']
    installed = list((Path(prefix) / 'conda-meta').glob('nextflow-*.json'))
    if len(installed) != 1 or json.loads(installed[0].read_text()).get('version') != version:
        parser.error('host Nextflow environment does not match the configured version')
    expected = sha(binary)
    protected = immutable + [str(p) for p in sealed]
    engine = guard(iteration / 'metadata/nextflow' / name, root, protected)
    logs = guard((args.logdir or iteration / 'logs/nextflow') / name, root, protected)
    # Custom log locations must also respect iteration ownership.
    if iteration not in logs.parents:
        parser.error(f'logs must stay under the producing {kind}')
    # What the workflow asks for: GPUs (label 'gpu' or 'process_gpu', or an accelerator directive) and
    # declared images (label 'image_<name>'). The workflow and every .nf file beside it are read.
    scripts_dir = iteration / 'scripts'
    nf_text = '\n'.join(t.read_text(errors='replace') for t in [workflow] + (
        sorted(scripts_dir.rglob('*.nf')) if scripts_dir.is_dir() else []) if t.is_file())
    labels = set(re.findall(r'\blabel\s*\(?\s*[\'"]([A-Za-z0-9_]+)[\'"]', nf_text))
    gpu = bool(labels & set(GPU_LABELS)) or bool(re.search(r'^\s*accelerator\b', nf_text, re.M))
    images = {}
    for label in sorted(l for l in labels if l.startswith('image_')):
        declared = site.get(label)
        if not declared:
            parser.error(f"process label '{label}' needs {label} = <image.sif> and {label}_sha256 in site.md")
        if '://' in declared:
            parser.error(f'{label} must be a local image file with {label}_sha256; remote references are not '
                         'pinned for workflow tasks')
        path = Path(declared) if Path(declared).is_absolute() else root / site.get('image_dir', '.arh/images') / declared
        if not path.is_file() or sha(path) != site.get(label + '_sha256'):
            parser.error(f'{label}: image missing or its digest does not match {label}_sha256')
        env_path = site.get(label + '_path')
        if not env_path:          # the image's own PATH; the runtime prefix's would hide its tools
            try:
                probe = subprocess.run(['singularity', 'exec', '--cleanenv', '--containall', str(path), '/bin/sh', '-c',
                                        'printf %s "$PATH"'], capture_output=True, text=True, timeout=300)
            except (OSError, subprocess.TimeoutExpired):
                probe = None
            env_path = probe.stdout.strip() if probe else ''
            if not probe or probe.returncode or not env_path:
                parser.error(f'could not read the PATH inside {path}; declare {label}_path in site.md')
        # The image's tools come first; the task environment's bin/ follows, because Nextflow needs `ps`
        # in every container to collect task metrics and many tool images do not ship it.
        if site.get('runtime_prefix'):
            env_path += ':' + site['runtime_prefix'] + '/bin'
        images[label] = dict(image=str(path), sha256=sha(path), path=env_path)
    engine.mkdir(parents=True, exist_ok=True)
    logs.mkdir(parents=True, exist_ok=True)
    lock = engine / '.launch-lock'
    if kind == 'iteration' and not os.environ.get('ARH_DETACHED'):    # a detached child's caller did it
        try:
            lease.touch(iteration, 'arh submit ' + name, dict(agent=os.environ.get('ARH_LEASE_AGENT', '?'),
                                                             user=os.environ.get('USER', 'unknown'),
                                                             host=os.uname().nodename,
                                                             session=os.environ.get('ARH_SESSION') or None))
        except lease.Refused as refused:
            sys.exit(f'arh: {refused}')
    if args.detach:
        return detach(lock, logs, iteration, kind)
    # A declared input that failed its last integrity check is named in every run that can read it.
    checked = inputs.summary(root)
    if checked and checked['failed']:
        print('arh: declared inputs failed their last integrity check (arh inputs list): '
              + ', '.join(checked['failed'][:3]) + (' …' if len(checked['failed']) > 3 else ''), file=sys.stderr)
    try:
        acquire(lock, what='launch lock')
    except Held as held:
        parser.error('this named workflow is already running; inspect .launch-lock before recovery'
                     + (f'{held}; stop it with kill -TERM' if str(held) else ''))
    try:
        attempt = Path(tempfile.mkdtemp(prefix='attempt-', dir=logs))
        if os.environ.get('ARH_DETACHED'):
            # The detached log otherwise held only arh's warnings; the live log is in the attempt (#71).
            print(f'arh: attempt {attempt}; live log {attempt / "nextflow.log"}, trace {attempt / "trace.tsv"}',
                  file=sys.stderr, flush=True)
        env = dict(os.environ, NXF_HOME=str(root / '.arh/nextflow'), NXF_VER=version,
                   NXF_ANSI_LOG='false', NXF_DISABLE_CHECK_LATEST='true', NXF_OFFLINE='true')
        # Plugins/images must be staged in advance for offline execution.
        site_nf = root / '.arh/config/nextflow.config'
        generated = attempt / 'execution.config'
        executor = site.get('scheduler', 'local')
        if executor not in ('local', 'slurm', 'pbs'):
            parser.error('scheduler must be local, slurm or pbs')
        # report.html and timeline.html are ~99% of a submission's evidence bytes (1.9 MB per run);
        # the ARH receipt and trace.tsv are always kept.
        reports = site.get('nextflow_reports') or 'html'
        if reports not in ('html', 'gzip', 'none'):
            parser.error('nextflow_reports must be html, gzip or none')
        runtime = 'singularity'
        if not shutil.which('singularity'):
            parser.error('Singularity must be available on the host')
        if executor == 'slurm':
            for tool in ('sbatch', 'squeue', 'scancel'):
                if not shutil.which(tool):
                    parser.error('Slurm command missing from host PATH: ' + tool)
        if not Path(image).is_file() or sha(image) != site.get('runtime_sha256'):
            parser.error('runtime SIF missing or digest mismatch')
        # task_project_access = ro: a task reads the project but writes only its own iteration's results/
        # and its run's work directory, so it cannot change a frozen plan, a review, a receipt or another
        # iteration (external review of v0.3.0: "tasks can write the record"). rw keeps the old behaviour.
        access = project.get('task_project_access') or 'rw'
        if access not in ('rw', 'ro'):
            parser.error('task_project_access must be rw or ro')
        if access == 'ro':
            writable = [guard(iteration / 'results', root, protected), engine]
            writable[0].mkdir(parents=True, exist_ok=True)
            binds = [f'{root}:{root}:ro'] + [f'{w}:{w}:rw' for w in writable]
        else:
            binds = [str(root) + ':' + str(root) + ':rw']
        task_prefix = site.get('runtime_prefix')
        if task_prefix:
            binds.append(task_prefix + ':' + task_prefix + ':ro')
        for item in immutable:
            source = Path(item)
            source = (source if source.is_absolute() else root / source).resolve()
            binds.append(str(source) + ':' + str(source) + ':ro')
        # Sealed inputs: bound read-only for a frozen confirmation; otherwise covered by an empty
        # mount, which also hides them inside a broader immutable input. Nextflow's automounts bind a
        # staged input's directory before these options and Singularity keeps the first bind of a
        # target, so automounts are off for a run that may not read them.
        masked = []
        binds += [f'{p}:{p}:ro' for p in readable]
        for source, target in freeze.masks(root, hidden):
            binds.append(f'{source}:{target}:ro')
            masked.append(str(target))
        options = ' '.join('--bind ' + shlex.quote(bind) for bind in binds)
        if task_prefix:
            options += ' --env ' + shlex.quote('PATH=' + task_prefix + '/bin:/usr/local/bin:/usr/bin:/bin')
        def has(label):
            return f'(task.label ?: []).contains({literal(label)})'
        container = literal(image)
        for label, spec in sorted(images.items(), reverse=True):
            container = f"({has(label)} ? {literal(spec['image'])} : {container})"
        container_options = "''"
        for label, spec in sorted(images.items(), reverse=True):
            container_options = f"({has(label)} ? {literal('--env PATH=' + spec['path'])} : {container_options})"
        if gpu:
            container_options += f" + ({WANTS_GPU} ? ' --nv' : '')"
        # task_retries = N retries a failed task up to N times, for sites where tasks fail on cluster
        # events: one task exiting 1 with no traceback stopped a 16-task run while nobody watched
        # (field feedback #63). Off by default; each retry is in trace.tsv and the receipt says so.
        retries = site.get('task_retries') or '0'
        if not retries.isdigit():
            parser.error('task_retries must be a whole number')
        strategy = ('"terminate"' if retries == '0'
                    else f"{{ task.attempt <= {int(retries)} ? 'retry' : 'terminate' }}")
        lines = [f'process.executor = {literal(executor)}', f'process.errorStrategy = {strategy}',
                 f'process.maxRetries = {int(retries)}', 'tower.enabled = false', 'wave.enabled = false',
                 f'process.container = {{ {container} }}' if images else f'process.container = {literal(image)}',
                 'singularity.enabled = true',
                 f"singularity.autoMounts = {'false' if hidden else 'true'}",
                 f'singularity.runOptions = {literal(options)}',
                 # The default fields, plus the image each task actually ran in.
                 "trace.fields = 'task_id,hash,native_id,name,status,exit,submit,duration,realtime,"
                 "%cpu,peak_rss,peak_vmem,rchar,wchar,container'"]
        if images or gpu:
            lines.append(f'process.containerOptions = {{ {container_options} }}')
        if executor == 'slurm':
            lines += slurm_settings(site, gpu)
        elif gpu and executor == 'pbs':
            print('arh: GPU tasks get --nv, but no PBS GPU request is generated; set it in the workflow', file=sys.stderr)
        generated.write_text('\n'.join(lines) + '\n')
        configs = [str(site_nf)] if site_nf.is_file() else []
        configs.append(str(generated))
        cmd = [str(Path(binary).resolve()), '-log', str(attempt / 'nextflow.log'), '-C', ','.join(configs),
               'run', str(workflow if workflow.suffix == '.nf' else home / 'workflows/script.nf'),
               '-work-dir', str(engine / 'work'), '-with-trace', str(attempt / 'trace.tsv'),
               '-ansi-log', 'false']
        if reports != 'none':
            cmd += ['-with-report', str(attempt / 'report.html'), '-with-timeline', str(attempt / 'timeline.html')]
        if args.resume:
            cmd.append('-resume')
        if args.params:
            params = args.params.resolve()
            if not params.is_file():
                parser.error('params file missing')
            cmd += ['-params-file', str(params)]
        if workflow.suffix == '.sh':
            cmd += ['--arh_script', str(workflow), '--arh_project', str(root)]
        else:
            cmd += ['--outdir', str(iteration / 'results' / name)]
        # Workflows call the iteration's scripts by path, and those scripts are not Nextflow inputs:
        # without their hashes two receipts of runs that did different things can look identical.
        scripts = iteration / 'scripts'
        script_sha256 = ({str(p.relative_to(root)): sha(p) for p in sorted(scripts.rglob('*'))
                          if p.is_file() and '__pycache__' not in p.parts} if scripts.is_dir() else {})
        # Other iterations' scripts the workflow or its scripts name: hashed whether or not declared.
        referenced = imports.referenced(root, iteration, [workflow] + [root / p for p in script_sha256],
                                        project.get('iterations_dir', 'iterations'),
                                        project.get('verification_dir', 'verification'))
        undeclared = sorted(set(referenced) - set(import_sha256))
        # A workflow that passes another iteration's scripts/ directory as a parameter references every
        # file in it; all are hashed, but only those named by file name are worth a warning, or the one
        # real undeclared import is lost among files that never run (field feedback #64, #72, #81).
        named_text = '\n'.join(t.read_text(errors='replace') for t in [workflow] + [root / p for p in script_sha256]
                                + ([args.params.resolve()] if args.params else []) if t.is_file())
        quiet = [r for r in undeclared if Path(r).name not in named_text]
        undeclared = [r for r in undeclared if r not in quiet]
        if quiet:
            print(f'arh: {len(quiet)} other file(s) under a scripts/ directory the workflow names are hashed in '
                  'run.json as referenced_sha256; none is named by file name, so none is listed', file=sys.stderr)
        if undeclared:
            print('arh: the scripts name code from other iterations that the pre-declaration does not declare '
                  'as imports (hashed in run.json as referenced_sha256): ' + ', '.join(undeclared[:5])
                  + (' …' if len(undeclared) > 5 else ''), file=sys.stderr)
        record = dict(engine='nextflow', version=version, executable_sha256=expected, environment_prefix=prefix,
                      owner=dict(kind=kind, path=str(iteration.relative_to(root))),
                      workflow=str(workflow.relative_to(root)) if root in workflow.parents else str(workflow),
                      workflow_sha256=sha(workflow),
                      script_sha256=script_sha256, import_sha256=import_sha256, referenced_sha256=referenced,
                      predeclaration_sha256=sha(plan) if plan else None,
                      params_sha256=sha(args.params) if args.params else None,
                      config_sha256={str(p): sha(p) for p in map(Path, configs)},
                      executor=executor, runtime=runtime, image=image or None, image_sha256=sha(image),
                      driver_package_sha256=sha(installed[0]),
                      environment_locks={p.name: sha(p) for p in (root / '.arh').glob('*explicit.lock')},
                      resume=args.resume, reports=reports, command=cmd, started=datetime.now(timezone.utc).isoformat(),
                      task_project_access=access,
                      # Who launched it (S11): a project shared by several people or accounts.
                      user=os.environ.get('USER', 'unknown'), host=os.uname().nodename,
                      session=os.environ.get('ARH_SESSION') or None)
        if checked:
            record['input_checks'] = checked
        if pinned_changed and policy != 'off':
            record['scripts_changed_since_freeze'] = pinned_changed
        if retries != '0':
            record['task_retries'] = int(retries)
        if images:
            record['images'] = images
        if gpu:
            record['gpu'] = {k: site.get(k) or None for k in ('gpu_partition', 'gpu_type', 'gpu_constraint', 'gpu_extra')}
        if frozen_state != 'none':
            record['freeze_sha256'] = freeze_sha
        if sealed:
            record['sealed_inputs'] = dict(read=[str(p) for p in readable], masked=masked)
        receipt = attempt / 'run.json'
        receipt.write_text(json.dumps(record, indent=2) + '\n')
        if unsealed:
            freeze.record_unseal(root, iteration.name[9:], name, attempt.name, readable, freeze_sha)
        received = []
        with (attempt / 'console.log').open('w') as output:
            proc = subprocess.Popen(cmd, cwd=engine, env=env, stdout=output, stderr=subprocess.STDOUT)

            def forward(signum, frame):
                # Stopping the wrapper must stop Nextflow (which cancels its jobs) and still reach
                # the `finally` that releases the launch lock. A second signal escalates.
                received.append(signal.Signals(signum))
                proc.send_signal(signal.SIGTERM if len(received) == 1 else signal.SIGKILL)

            handlers = {s: signal.signal(s, forward) for s in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)}
            try:
                returncode = proc.wait()
            finally:
                for s, handler in handlers.items():
                    signal.signal(s, handler)
        if reports == 'gzip':
            for page in ('report.html', 'timeline.html'):
                html = attempt / page
                if html.is_file():
                    with html.open('rb') as source, gzip.open(str(html) + '.gz', 'wb') as target:
                        shutil.copyfileobj(source, target)
                    html.unlink()
        record.update(exit_code=returncode, finished=datetime.now(timezone.utc).isoformat())
        if received:
            record['signal'] = received[0].name
            returncode = returncode or 128 + received[0].value
        hook = args.on_exit or site.get('on_exit')
        if hook:
            record['on_exit'] = notify(hook, record, attempt, name, iteration, root)
        receipt.write_text(json.dumps(record, indent=2) + '\n')
        print(attempt)
        print(f'arh: Nextflow exit={record["exit_code"]}; trace and logs: {attempt}'
              + (f'; stopped by {record["signal"]}' if received else ''), file=sys.stderr)
        if returncode:
            print('\n'.join((attempt / 'console.log').read_text().splitlines()[-20:]), file=sys.stderr)
        return returncode
    finally:
        release(lock)


if __name__ == '__main__':
    sys.exit(run())
