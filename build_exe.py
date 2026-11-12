"""Build the GUI executable on the current Windows or Linux host."""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys
import venv


ROOT = Path(__file__).resolve().parent


def run(command: list[str]) -> None:
    print('+ ' + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skip-install', action='store_true',
                        help='Reuse installed dependencies without accessing pip.')
    parser.add_argument('--current-env', action='store_true',
                        help='Use the current Python environment instead of .venv-build.')
    args = parser.parse_args()
    if sys.platform not in ('win32', 'linux'):
        parser.error('Run on Windows or Linux to build a native executable.')
    if sys.version_info < (3, 10):
        parser.error('Python 3.10 or newer is required (3.12 recommended).')

    platform = 'windows' if sys.platform == 'win32' else 'linux'
    if platform == 'windows' and not (ROOT / 'libusb-1.0.dll').is_file():
        parser.error('Missing libusb-1.0.dll in the project root.')
    python = Path(sys.executable)
    if not args.current_env:
        env_dir = ROOT / '.venv-build' / platform
        python = env_dir / ('Scripts/python.exe' if platform == 'windows' else 'bin/python')
        has_pip = python.is_file() and subprocess.run(
            [str(python), '-m', 'pip', '--version'], cwd=ROOT,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if not has_pip:
            if args.skip_install:
                parser.error('Build environment is missing; run once without --skip-install.')
            print(f'Creating build environment: {env_dir}', flush=True)
            try:
                venv.EnvBuilder(with_pip=True).create(env_dir)
            except (Exception, SystemExit) as exc:
                raise RuntimeError('Cannot create the build environment. On Debian/Ubuntu, '
                                   'install python3-venv first.') from exc

    if not args.skip_install:
        run([str(python), '-m', 'pip', 'install', '--upgrade', 'pip'])
        run([str(python), '-m', 'pip', 'install', '-r', str(ROOT / 'requirements.txt'),
             'pyinstaller>=6.0'])

    # Fail early with a clear import error when --skip-install is used too soon.
    run([str(python), '-c', 'import PyInstaller, PySide6.QtWidgets, usb.core'])
    output = ROOT / 'dist' / platform
    work = ROOT / 'build' / 'packaging' / platform
    run([str(python), '-m', 'PyInstaller', '--clean', '--noconfirm',
         '--distpath', str(output), '--workpath', str(work),
         str(ROOT / 'CANable2.5.spec')])
    executable = output / ('CANable2.5.exe' if platform == 'windows' else 'CANable2.5')
    if not executable.is_file():
        raise RuntimeError(f'Build finished without the expected executable: {executable}')
    print(f'\nBuild succeeded: {executable}', flush=True)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f'\nBuild failed (exit code {exc.returncode}). See the output above.', file=sys.stderr)
        sys.exit(1)
    except (OSError, RuntimeError) as exc:
        print(f'\nBuild failed: {exc}', file=sys.stderr)
        sys.exit(1)
