"""Package the preserved Mac sources without reading a user's installed Data."""
from pathlib import Path
import argparse
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def run(*args):
    subprocess.run([str(a) for a in args], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--opus', type=Path)
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        parser.error('This baseline targets Apple Silicon macOS 14 or later.')
    out = args.output.resolve()
    if out.exists():
        parser.error('Output already exists. Choose a new folder; existing data is never overwritten.')
    opus = args.opus or Path('/opt/homebrew/opt/opus/lib/libopus.0.dylib')
    if not opus.is_file():
        parser.error('Install Opus or pass --opus /absolute/path/libopus.0.dylib.')
    work = ROOT / 'build' / 'macos'
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True)
    app = out / '小哈语音.app'
    # The original native build source is preserved byte for byte.
    run(sys.executable, ROOT / 'mac-prototype/build.py', '--output', app)
    command = [sys.executable, '-m', 'PyInstaller', '--noconfirm', '--clean',
               '--onedir', '--name', 'xiaoha-runtime', '--distpath', out / 'Runtime',
               '--workpath', work / 'pyinstaller', '--specpath', work,
               '--paths', ROOT / 'sync-suite', '--paths', ROOT / 'ime-channel-test']
    for name in ('desktop', 'server', 'keyring.backends', 'uvicorn', 'python_socks'):
        command.extend(['--collect-submodules', name])
    for name in ('jieba', 'certifi'):
        command.extend(['--collect-data', name])
    command.extend(['--copy-metadata', 'keyring', ROOT / 'toolkit/runtime.py'])
    run(*command)
    engine = out / 'Components/engine'
    engine.mkdir(parents=True)
    for name in ('channel_probe.py', 'personalization.py', 'volcengine_asr.py',
                 'protocol-constants.json', 'UPSTREAM-LICENSE-MIT.txt'):
        shutil.copy2(ROOT / 'ime-channel-test' / name, engine / name)
    shutil.copy2(opus, engine / 'libopus.0.dylib')
    run('/usr/bin/codesign', '--force', '--sign', '-', engine / 'libopus.0.dylib')
    workbench = out / 'Components/workbench'
    for name in ('desktop', 'web', 'server'):
        shutil.copytree(ROOT / 'sync-suite' / name, workbench / name,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'private',
                                                     'personal-fixtures', 'clipboard-macos'))
    run('/usr/bin/swiftc', workbench / 'desktop/ClipboardMac.swift',
        '-o', workbench / 'desktop/clipboard-macos', '-framework', 'AppKit')
    (out / 'Data').mkdir(mode=0o700)
    (out / 'Data/.keep').touch()
    manifest = {'format': 1, 'name': '小哈语音', 'version': '0.3.8',
                'platform': 'macOS-arm64', 'data': 'Data',
                'runtime': 'Runtime/xiaoha-runtime/xiaoha-runtime', 'cloud_deployed': False}
    (out / 'toolkit.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    shutil.copytree(ROOT / 'LICENSES', out / 'LICENSES')
    # Include licenses for the dependencies actually installed in this build too.
    for distribution in importlib.metadata.distributions():
        for item in distribution.files or []:
            if '.dist-info/' not in str(item) or not any(
                    word in str(item).lower() for word in ('license', 'copying')):
                continue
            original = distribution.locate_file(item)
            if original.is_file():
                dest = out / 'LICENSES' / distribution.metadata['Name'] / str(item).split('.dist-info/', 1)[1]
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, dest)
    for candidate in (Path(sys.base_prefix) / 'LICENSE.txt',
                      Path(sys.base_prefix) / 'Resources/English.lproj/License.rtf'):
        if candidate.is_file():
            shutil.copy2(candidate, out / 'LICENSES' / ('Python-' + candidate.name))
    sources = out / '维护源码'
    sources.mkdir()
    for original in (ROOT / 'mac-prototype').iterdir():
        if original.is_file() and (original.suffix == '.swift' or original.name == 'build.py'):
            shutil.copy2(original, sources / original.name)
    shutil.copy2(ROOT / 'toolkit/runtime.py', sources / 'runtime.py')
    shutil.copy2(ROOT / 'docs/数据与恢复说明.md', out / '数据与恢复说明.md')
    (out / '使用说明.md').write_text(
        '# 小哈语音工具包\n\n保留整个文件夹，双击“小哈语音.app”。首次请配置自己的识别通道与系统权限。\n'
        'Data 是自己的记录与设置；本包不含个人资料。完整使用、构建与许可说明见项目仓库。\n')
    print(json.dumps({'built': True, 'version': '0.3.8', 'build': '12',
                      'personal_data_copied': False, 'app_launched': False}, ensure_ascii=False))


if __name__ == '__main__':
    main()
