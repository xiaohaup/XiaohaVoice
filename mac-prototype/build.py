"""Build the authorized local Mac prototype; no launch, mic access or settings change."""
from pathlib import Path
import argparse,hashlib,json,plistlib,subprocess
r=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);args=parser.parse_args()
bundle=(args.output.resolve() if args.output else r/'小哈语音.app')/'Contents'
(bundle/'MacOS').mkdir(parents=True,exist_ok=True)
bridge=r.parent/'ime-channel-test'
p={'CFBundleExecutable':'XiaohaVoice','CFBundleIdentifier':'com.xiaoha.voice','CFBundleName':'小哈语音',
   'CFBundleDisplayName':'小哈语音','CFBundlePackageType':'APPL','CFBundleShortVersionString':'0.3.8','CFBundleVersion':'12',
   'LSUIElement':True,'LSMinimumSystemVersion':'14.0','NSHighResolutionCapable':True,
   'NSMicrophoneUsageDescription':'按已设快捷键或开始按钮后，使用Mac内建麦克风，并将声音发送至你选定的语音通道；正常录音不另存音频，失败或未完成音频仅在本机保留供恢复。',
   'PrototypeRoot':str(r),'BridgeRoot':str(bridge),'NSAppTransportSecurity':{'NSAllowsLocalNetworking':True},'CFBundleIconFile':'XiaohaVoice.icns'}
(bundle/'Info.plist').write_bytes(plistlib.dumps(p))
(bundle/'Resources').mkdir(exist_ok=True)
(bundle/'Resources/UPSTREAM-LICENSE-MIT.txt').write_bytes((bridge/'UPSTREAM-LICENSE-MIT.txt').read_bytes())
iconset=bundle.parent.parent/'XiaohaVoice.iconset'
subprocess.run(['/usr/bin/swift','-module-cache-path',str(r.parent/'diagnostics/module-cache'),str(r/'Icon.swift'),str(iconset)],check=True)
subprocess.run(['/usr/bin/iconutil','-c','icns',str(iconset),'-o',str(bundle/'Resources/XiaohaVoice.icns')],check=True)
files=['RuntimePaths.swift','EventLog.swift','Toolkit.swift','Gesture.swift','Hotkey.swift','AudioRecorder.swift','History.swift','Paste.swift','Session.swift','Recovery.swift','CapsuleTheme.swift','Capsule.swift','Bridge.swift','WindowChrome.swift','Desktop.swift','main.swift']
cmd=['/usr/bin/swiftc','-target','arm64-apple-macosx14.0','-module-cache-path',str(r.parent/'diagnostics/module-cache')]
cmd += [str(r/x) for x in files]
cmd += ['-o',str(bundle/'MacOS/XiaohaVoice'),'-framework','AppKit','-framework','AVFoundation','-framework','CoreMedia','-framework','ApplicationServices','-framework','WebKit']
subprocess.run(cmd,check=True)
subprocess.run(['/usr/bin/codesign','--force','--sign','-',str(bundle.parent)],check=True,capture_output=True)
subprocess.run(['/usr/bin/codesign','--verify','--deep','--strict',str(bundle.parent)],check=True)
result={'built':True,'launched':False,'version':'0.3.8','source_sha256':{x:hashlib.sha256((r/x).read_bytes()).hexdigest() for x in files},'binary_sha256':hashlib.sha256((bundle/'MacOS/XiaohaVoice').read_bytes()).hexdigest(),'mic_permission_granted_by_agent':False,'input_monitoring_granted_by_agent':False}
(bundle.parent.parent/'build-receipt.json' if args.output else r/'build-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'built':True,'source_files':len(files),'binary_sha256':result['binary_sha256']}))
