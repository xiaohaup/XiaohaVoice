import AppKit
import AVFoundation

final class VoiceApp:NSObject,NSApplicationDelegate {
    let root=URL(fileURLWithPath:Bundle.main.infoDictionary!["PrototypeRoot"] as! String)
    let bridgeRoot=RuntimePaths.engine
    lazy var workbench=DesktopWorkbench(root:RuntimePaths.workbench,history:localDirectory.appendingPathComponent("history.json"))
    lazy var toolkit=ToolkitManager(workbench:workbench)
    let capsule=Capsule(), recorder=AudioRecorder(), hotkey=RightOptionMonitor()
    lazy var capsuleThemes=CapsuleThemePreferences(directory:localDirectory,catalogPath:RuntimePaths.workbench.appendingPathComponent("web/capsule-palettes.json"))
    let autoPaste=AutoPaste()
    lazy var recovery=RecoveryArchive(directory:localDirectory.appendingPathComponent("recovery"))
    var lastStoppedSession:UUID?
    var deliveries=OrderedDeliveries()
    var pasteTestGeneration=0,pasteTestRunning=false
    var pasteTestStatus="",lastPasteStatus=""
    var history:HistoryStore?
    var historyError:String?
    var item:NSStatusItem!
    var menu=NSMenu()
    var toggleItem:NSMenuItem!
    var keyItem:NSMenuItem!
    var active:VoiceSession?
    var displayed:VoiceSession?
    var sessions=[UUID:VoiceSession]()
    var stoppingCapture=false, pendingStart=false
    var wantsHotkey=false
    var silentStartup=true,dockVisible=false
    var shortcutCaptureUntil=Date.distantPast
    var timer:Timer?
    var dashboard:NSWindow?
    let stats=NSTextField(labelWithString:"")
    let help=NSTextField(wrappingLabelWithString:"")
    let result=NSTextView()
    let selector=NSPopUpButton()
    let historyCopyButton=NSButton(title:"复制所选全文",target:nil,action:nil)
    let dashboardHotkeyButton=NSButton(title:"启用右 Option",target:nil,action:nil)
    let pastePermissionButton=NSButton(title:"启用自动粘贴",target:nil,action:nil)
    var recordingIndicator:Bool?
    var lastMetrics=[String:Any]()
    var localDirectory:URL {RuntimePaths.data}
    var shortcutSeparated:Bool {
        let p=localDirectory.appendingPathComponent("native-shortcut.json")
        guard let d=try? Data(contentsOf:p),let o=(try? JSONSerialization.jsonObject(with:d)) as? [String:Any] else{return false}
        return o["separated"] as? Bool == true
    }
    var shortcutSafe:Bool {hotkey.shortcut.keyCode != 61 || shortcutSeparated}
    func applicationDidFinishLaunching(_ note:Notification) {
        if let other=NSRunningApplication.runningApplications(withBundleIdentifier:"com.xiaoha.voice").first(where:{$0.processIdentifier != ProcessInfo.processInfo.processIdentifier}) {other.activate(options:[.activateAllWindows]);NSApp.terminate(nil);return}
        NSApp.setActivationPolicy(.accessory)
        do {history=try HistoryStore(directory:localDirectory)} catch {historyError="本机历史暂不可用，已有文件保留。"}
        do {for session in try recovery.load(excluding:Set(history?.records.map{$0.id} ?? [])){sessions[session.id]=session}} catch {historyError="有待恢复的录音无法读取，原文件已保留。"}
        let path=localDirectory.appendingPathComponent("settings.json")
        if let data=try? Data(contentsOf:path),let saved=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any] {wantsHotkey=saved["right_option_enabled"] as? Bool ?? false
            silentStartup=saved["silent_startup"] as? Bool ?? true;dockVisible=saved["show_dock"] as? Bool ?? false
            if let v=saved["shortcut"],let d=try? JSONSerialization.data(withJSONObject:v),let c=try? JSONDecoder().decode(VoiceShortcut.self,from:d),c.valid{hotkey.shortcut=c}
        }
        workbench.keepDock=dockVisible;NSApp.setActivationPolicy(dockVisible ? .regular : .accessory)
        try? workbench.login.migrateAliasIfNeeded()
        workbench.toolkit=toolkit
        toolkit.prepare={ [weak self] in
            guard let self=self,self.active==nil,!self.stoppingCapture,!self.sessions.values.contains(where:{!$0.complete && $0.failure==nil}) else{throw NSError(domain:"小哈语音",code:1,userInfo:[NSLocalizedDescriptionKey:"请先结束录音并等待识别完成，再备份或恢复"])}
            for session in self.pendingSessions{try self.recovery.save(session)};self.saveSettings()
        }
        toolkit.restored={ [weak self] in
            guard let self=self else{return};self.history=try HistoryStore(directory:self.localDirectory)
            let restored=try self.recovery.load(excluding:Set(self.history?.records.map{$0.id} ?? []));self.sessions=Dictionary(uniqueKeysWithValues:restored.map{($0.id,$0)});self.displayed=nil;self.refresh();self.refreshHistory()
        }
        item=NSStatusBar.system.statusItem(withLength:NSStatusItem.squareLength)
        item.button?.image=NSImage(systemSymbolName:"waveform",accessibilityDescription:"小哈语音")
        item.button?.toolTip="小哈语音"
        addMenu("打开小哈语音",#selector(openWorkbench));addMenu("账号同步与词库",#selector(openAccount))
        menu.addItem(.separator());toggleItem=addMenu("开始说话",#selector(toggle));addMenu("显示胶囊",#selector(showCapsule))
        menu.addItem(.separator());keyItem=addMenu("启用右 Option",#selector(enableHotkey))
        addMenu("本机历史",#selector(openHistory));addMenu("语音输入",#selector(openVoiceSettings));addMenu("词库纠正",#selector(openWordSettings));addMenu("应用设置",#selector(openSettings));menu.addItem(.separator());addMenu("退出小哈语音",#selector(quit))
        item.menu=menu
        hotkey.onToggle={ [weak self] in self?.toggle() }
        hotkey.shouldCancel={ [weak self] in guard let self=self else{return false};return self.active != nil || (self.displayed.map{!$0.complete && !$0.restored && $0.failure==nil} ?? false) }
        hotkey.onCancel={ [weak self] in self?.cancelCurrent() }
        hotkey.onMouseCapture={ [weak self] button in guard let self=self,Date()<self.shortcutCaptureUntil else{return};self.workbench.capturedMouseShortcut(["keyCode":-1,"modifiers":0,"mouseButton":button,"label":"鼠标侧键 \(button+1)"]) }
        capsule.onDismiss={ [weak self] in self?.dismissCapsule() }
        capsule.onCopy={ [weak self] in self?.copyDisplayed() }
        capsule.onRetry={ [weak self] in if let s=self?.displayed {self?.retry(s)} }
        recorder.onError={ [weak self] message in
            guard let self=self,let s=self.active else{return}
            s.connectionFailed(message);self.stopRecording();self.refresh()
        }
        timer=Timer.scheduledTimer(withTimeInterval:0.2,repeats:true) { [weak self] _ in
            guard let self=self else{return}
            if self.wantsHotkey && !self.hotkey.enabled && RightOptionMonitor.authorized && self.shortcutSafe {_ = self.hotkey.start()}
            if self.hotkey.suspended && Date()>self.shortcutCaptureUntil{self.hotkey.suspended=false}
            self.refresh()
        }
        let mainMenu=NSMenu(),appMenu=NSMenu()
        let appRoot=NSMenuItem();appRoot.submenu=appMenu;mainMenu.addItem(appRoot)
        let exit=NSMenuItem(title:"退出小哈语音",action:#selector(NSApplication.terminate(_:)),keyEquivalent:"q")
        appMenu.addItem(exit);NSApp.mainMenu=mainMenu
        let edit=NSMenu(title:"编辑"),editRoot=NSMenuItem(title:"编辑",action:nil,keyEquivalent:"");editRoot.submenu=edit;mainMenu.addItem(editRoot)
        for (title,selector,key) in [("撤销","undo:","z"),("重做","redo:","Z"),("剪切","cut:","x"),("复制","copy:","c"),("粘贴","paste:","v"),("全选","selectAll:","a")] {
            let entry=NSMenuItem(title:title,action:Selector(selector),keyEquivalent:key.lowercased());entry.keyEquivalentModifierMask=key=="Z" ? [.command,.shift] : [.command];edit.addItem(entry)
        }
        workbench.state={ [weak self] in guard let self=self else{return [:]};return ["version":Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "0.3.8","capsule_theme":self.capsuleThemes.mode.rawValue,"recording":self.active != nil,"hotkey":self.hotkey.enabled,"microphone":AVCaptureDevice.authorizationStatus(for:.audio) == .authorized,"input_monitoring":RightOptionMonitor.authorized,"accessibility":AutoPaste.authorized,"silent_startup":self.silentStartup,"show_dock":self.dockVisible,"shortcut":self.hotkey.shortcut.label,"hotkey_enabled":self.wantsHotkey,"pending_count":self.pendingSessions.count,"paste_test_running":self.pasteTestRunning,"paste_test_status":self.pasteTestStatus,"last_paste_status":self.lastPasteStatus,"toolkit_busy":self.toolkit.busy,"toolkit_status":self.toolkit.status] }
        workbench.configure={ [weak self] command,value in
            guard let self=self else{return [:]}
            func invalid(_ message:String)->NSError{NSError(domain:"小哈语音",code:1,userInfo:[NSLocalizedDescriptionKey:message])}
            switch command {
            case "capsuleAppearance":
                if let theme=value["theme"] as? String{try self.capsuleThemes.preview(theme)}
                if let mode=value["mode"] as? String{try self.capsuleThemes.save(mode)}
                self.refresh()
                return ["mode":self.capsuleThemes.mode.rawValue,"resolved":self.capsuleThemes.resolved.rawValue]
            case "recovery":
                let formatter=ISO8601DateFormatter()
                return ["records":self.pendingSessions.map{session in ["id":session.id.uuidString,"created_at":formatter.string(from:session.createdAt),"seconds":session.seconds,"text":session.text,"retrying":session.failure == nil,"recording":self.active?.id==session.id] as [String:Any]}]
            case "retryRecovery","discardRecovery":
                guard self.active==nil else{throw invalid("请先结束当前录音，再处理恢复内容")}
                guard let raw=value["id"] as? String,let id=UUID(uuidString:raw),let session=self.sessions[id],!session.complete,!session.pcm.isEmpty else{throw invalid("这段录音已经处理，请刷新列表")}
                if command=="retryRecovery" {
                    guard session.failure != nil else{throw invalid("这段录音正在识别，请稍候")}
                    self.displayed=session;self.retry(session);self.capsule.show()
                } else {
                    guard value["confirmed"] as? Bool == true else{throw invalid("请先在工作台确认移到废纸篓")}
                    guard session.failure != nil else{throw invalid("这段录音正在识别，请稍候")}
                    try self.recovery.save(session);session.bridge?.cancel();try self.recovery.discard(id);self.sessions.removeValue(forKey:id)
                }
            case "startup":
                guard let silent=value["silent_startup"] as? Bool,let dock=value["show_dock"] as? Bool else{throw invalid("启动设置无效")}
                self.silentStartup=silent;self.dockVisible=dock;self.workbench.keepDock=dock;NSApp.setActivationPolicy(dock ? .regular : .accessory);self.saveSettings()
            case "beginShortcut":
                guard self.active==nil else{throw invalid("请结束当前录音后再修改快捷键")}
                self.hotkey.suspended=true;self.shortcutCaptureUntil=Date().addingTimeInterval(30)
            case "cancelShortcut":self.hotkey.suspended=false
            case "shortcut":
                guard self.active==nil else{throw invalid("请先结束当前录音")}
                guard let data=try? JSONSerialization.data(withJSONObject:value),let config=try? JSONDecoder().decode(VoiceShortcut.self,from:data),config.valid else{throw invalid("请选择单侧修饰键、功能键或组合键，避免普通打字触发")}
                guard ![59,62].contains(config.keyCode) else{throw invalid("左右 Control 暂留给豆包输入法，请选其他键避开冲突")}
                self.hotkey.shortcut=config;self.hotkey.suspended=false;self.wantsHotkey=true;self.saveSettings()
                if RightOptionMonitor.authorized{_ = self.hotkey.start()}
            default:throw invalid("设置无法识别")
            }
            return ["ok":true]
        }
        workbench.copyText={ [weak self] text in self?.autoPaste.clipboard.abandon();NSPasteboard.general.clearContents();NSPasteboard.general.setString(text,forType:.string) }
        workbench.action={ [weak self] command in
            guard let self=self else{return}
            switch command {
            case "previewCapsule":
                guard self.active==nil,!self.stoppingCapture,!self.sessions.values.contains(where:{!$0.complete && $0.failure==nil}) else{self.capsule.show();return}
                self.capsule.preview{[weak self] in self?.active==nil};self.refresh()
            case "pasteTest":self.testPaste()
            case "inputPermission":
                if !RightOptionMonitor.authorized {self.wantsHotkey=true;self.saveSettings();self.hotkey.requestPermission()}
                NSWorkspace.shared.open(URL(string:"x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent")!)
            case "pastePermission":if !AutoPaste.authorized {AutoPaste.requestPermission()} else {NSWorkspace.shared.open(URL(string:"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility")!)}
            case "microphoneSettings":
                if AVCaptureDevice.authorizationStatus(for:.audio) == .notDetermined {AVCaptureDevice.requestAccess(for:.audio){_ in}}
                else {NSWorkspace.shared.open(URL(string:"x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone")!)}
            default:break
            }
        }
        let intent=localDirectory.appendingPathComponent("desktop-install.json")
        if let data=try? Data(contentsOf:intent),var value=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any],value["enable_launch_at_login"] as? Bool == true,value["applied"] as? Bool != true {
            do {try workbench.login.set(true);value["applied"]=true;try JSONSerialization.data(withJSONObject:value).write(to:intent,options:.atomic)} catch {help.stringValue="自动启动暂未设置，可从偏好中重试。"}
        }
        refresh()
        if !CommandLine.arguments.contains("--login") || !silentStartup {openWorkbench()}
    }
    func applicationShouldHandleReopen(_ sender:NSApplication,hasVisibleWindows:Bool)->Bool {openWorkbench();return true}
    @objc func openWorkbench(){workbench.show()}
    @objc func openAccount(){workbench.show("/workbench#sync")}
    @objc func openRecovery(){workbench.show("/workbench#recovery")}
    @objc func openVoiceSettings(){workbench.show("/workbench#voice")}
    @objc func openWordSettings(){workbench.show("/workbench#text")}
    @objc func openHistory(){workbench.show("/workbench#history")}
    @objc func openSettings(){workbench.show("/workbench#app")}
    @objc func openStartup(){workbench.show("/workbench#app")}
    @discardableResult func addMenu(_ title:String,_ action:Selector)->NSMenuItem {
        let entry=NSMenuItem(title:title,action:action,keyEquivalent:"");entry.target=self;menu.addItem(entry);return entry
    }
    func saveSettings() {
        let path=localDirectory.appendingPathComponent("settings.json")
        do {
            let shortcut=try JSONSerialization.jsonObject(with:JSONEncoder().encode(hotkey.shortcut))
            try JSONSerialization.data(withJSONObject:["right_option_enabled":wantsHotkey,"silent_startup":silentStartup,"show_dock":dockVisible,"shortcut":shortcut]).write(to:path,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
        } catch {help.stringValue="设置暂未保存，当前会话仍可使用。"}
    }
    @objc func enableHotkey() {
        if hotkey.enabled {hotkey.stop();wantsHotkey=false;saveSettings();refresh();return}
        wantsHotkey=true;saveSettings()
        if !RightOptionMonitor.authorized {hotkey.requestPermission();showDashboard()}
        if !shortcutSafe {showDashboard();help.stringValue="右 Option 尚未接管：需先将原豆包输入法的语音快捷键避开。菜单栏“开始说话”现在即可使用。";return}
        if RightOptionMonitor.authorized {_ = hotkey.start()}
        refresh()
    }
    @objc func toggle() {
        if active != nil {stopRecording();return}
        if stoppingCapture {pendingStart=true;return}
        switch AVCaptureDevice.authorizationStatus(for:.audio) {
        case .authorized:startRecording()
        case .notDetermined:
            AVCaptureDevice.requestAccess(for:.audio) {ok in DispatchQueue.main.async {if ok {self.startRecording()} else {self.help.stringValue="麦克风未获允许；本次没有开始录音。";self.showDashboard()}}}
        default:help.stringValue="请在系统设置的麦克风权限中允许“小哈语音”。";showDashboard()
        }
    }
    func startRecording() {
        guard active == nil else{return}
        guard !toolkit.busy else{toolkit.status="正在备份或恢复，请稍后开始录音。";return}
        if pasteTestRunning {pasteTestGeneration+=1;pasteTestRunning=false;pasteTestStatus="测试已取消，语音录音优先。"}
        let s=VoiceSession();sessions[s.id]=s;active=s;displayed=s
        EventLog.record("capture",phase:"start")
        recorder.onAudio={ [weak self,weak s] data,rms in
            guard let self=self,let s=s else{return}
            s.append(data);self.flush(s)
            if self.displayed?.id == s.id {self.capsule.setLevel(rms)}
        }
        do {try recorder.start()} catch {
            s.requestStop();s.captureDidEnd();s.connectionFailed("无法打开 Mac 内建麦克风。")
            active=nil;refresh();showDashboard();return
        }
        connect(s);capsule.show();refresh()
    }
    func stopRecording() {
        guard let s=active else{return}
        EventLog.record("capture",phase:"stop",seconds:s.seconds)
        s.applicationName=NSWorkspace.shared.frontmostApplication?.localizedName
        s.pasteTarget=capturePasteTarget();lastStoppedSession=s.id
        deliveries.append(s.id)
        if NSWorkspace.shared.frontmostApplication?.processIdentifier==ProcessInfo.processInfo.processIdentifier {
            s.targetReady=false
            workbench.captureInput{[weak self,weak s] token in guard let s=s else{return};s.localInputToken=token;s.targetReady=true;self?.drainDeliveries()}
        }
        s.requestStop();active=nil;stoppingCapture=true
        recorder.stop { [weak self,weak s] in
            guard let self=self,let s=s else{return}
            s.captureDidEnd();self.stoppingCapture=false
            if s.pcm.isEmpty && !s.hasText {self.finishQuiet(s)}
            else {if s.failure != nil{self.resolveUnfinished(s,.failed)}else{self.flush(s);self.hideStoppedCapsule(s)};self.refresh()}
            if self.pendingStart {self.pendingStart=false;self.toggle()}
        }
        refresh()
    }
    func hideStoppedCapsule(_ s:VoiceSession){
        capsule.hide(after:1.2){[weak self,weak s] in guard let self=self,let s=s else{return false};return self.active==nil && self.displayed?.id==s.id}
    }
    func finishQuiet(_ s:VoiceSession){
        s.cancel();s.deliveryStatus="未听到内容，已结束";s.bridge?.cancel();workbench.historyChanged();refresh()
        drainDeliveries()
        capsule.hide(after:0){[weak self,weak s] in guard let self=self,let s=s else{return false};return self.active==nil && self.displayed?.id==s.id}
    }
    func handleEmptyResult(_ s:VoiceSession){
        guard s.captureEnded else{s.connectionFailed("识别提前结束，录音仍在继续");return}
        s.connectionFailed("没有识别到文字，音频已留在本机历史，可重试或移到废纸篓。")
        resolveUnfinished(s,.empty)
    }
    func resolveUnfinished(_ s:VoiceSession,_ ending:RecognitionEnding){
        guard !s.complete else{return}
        switch s.unfinishedDisposition(ending) {
        case .waitForStop:break
        case .closeQuietly:finishQuiet(s)
        case .retain:preserve(s);hideStoppedCapsule(s)
        }
        drainDeliveries()
    }
    func dismissCapsule(){
        if let s=active {
            s.cancel();s.deliveryStatus="已取消";s.bridge?.cancel();lastStoppedSession=s.id;active=nil;stoppingCapture=true
            recorder.stop{[weak self] in guard let self=self else{return};self.stoppingCapture=false;self.refresh();if self.pendingStart{self.pendingStart=false;self.toggle()}}
            workbench.historyChanged();refresh()
        }
        capsule.hide(after:0){[weak self] in self?.active==nil}
    }
    func cancelCurrent(){
        EventLog.record("capture",phase:"cancel")
        if active != nil{dismissCapsule();return}
        guard let s=displayed,!s.complete,!s.restored,s.failure==nil else{return}
        s.cancel();s.whenTargetReady=nil;s.deliveryStatus="已取消";s.bridge?.cancel();workbench.historyChanged();refresh();capsule.hide(after:0){true}
        drainDeliveries()
    }
    func connect(_ s:VoiceSession) {
        s.beginRetry();let generation=s.generation
        s.bridge?.cancel();let bridge=SpeechBridge();s.bridge=bridge
        bridge.onEvent={ [weak self,weak s] event in
            guard let self=self,let s=s,s.generation==generation else{return}
            switch event["event"] as? String {
            case "ready":s.bridgeReady=true;self.flush(s)
            case "interim","definite","final":if let text=event["text"] as? String {s.text=text}
            case "empty":self.handleEmptyResult(s)
            case "done":
                if s.captureEnded,(event["text"] as? String ?? s.text).trimmingCharacters(in:.whitespacesAndNewlines).isEmpty {self.handleEmptyResult(s);self.refresh();return}
                guard s.captureEnded,event["final_result_received"] as? Bool == true else {
                    s.connectionFailed("尚未收到最终稿，音频仍保留，可重试识别。")
                    self.resolveUnfinished(s,.failed)
                    self.refresh();return
                }
                let text=event["text"] as? String ?? s.text
                let duration=s.seconds
                do {
                    guard let history=self.history else{throw NSError(domain:"历史不可用",code:1)}
                    try history.append(VoiceRecord(id:s.id,createdAt:s.createdAt,text:text,seconds:duration,application:s.applicationName));self.workbench.historyChanged()
                } catch {self.historyError="本机历史保存失败，音频和草稿已保留，可重试。";s.connectionFailed(self.historyError!);self.preserve(s);self.refresh();return}
                s.finish(text);self.lastMetrics=event.filter {!["text","event"].contains($0.key)}
                self.drainDeliveries()
                self.refreshHistory()
            case "error":s.connectionFailed(event["message"] as? String ?? "识别连接中断");self.resolveUnfinished(s,.failed)
            default:break
            }
            self.refresh()
        }
        bridge.onExit={ [weak self,weak s] code in
            guard let self=self,let s=s,s.generation==generation else{return}
            if !s.complete && s.failure == nil {s.connectionFailed(code==0 ? "识别已断开，录音缓存仍保留。" : "识别连接中断，录音缓存仍保留。")}
            if s.failure != nil{self.resolveUnfinished(s,.failed)}
            // A recognition exit deliberately does not stop capture.
            self.refresh()
        }
        do {try bridge.start(root:bridgeRoot)} catch {s.connectionFailed("无法启动识别连接，录音缓存仍保留。")}
    }
    func flush(_ s:VoiceSession) {
        guard s.bridgeReady,!s.complete,s.failure == nil else{return}
        if s.sentOffset<s.pcm.count {
            let data=s.pcm.subdata(in:s.sentOffset..<s.pcm.count)
            s.bridge?.audio(data,replay:s.sentOffset==0 && data.count>16000)
            s.sentOffset=s.pcm.count
        }
        if s.captureEnded && !s.stopSent {s.stopSent=true;s.bridge?.finish()}
    }
    func retry(_ s:VoiceSession) {guard !s.complete,s.failure != nil else{return};connect(s);refresh()}
    func drainDeliveries(){
        let id=deliveries.begin(ready:{[self] id in sessions[id].map{$0.complete && $0.targetReady} ?? false},skip:{[self] id in sessions[id].map{$0.failure != nil || $0.deliveryStatus != nil} ?? true})
        if let id=id,let s=sessions[id]{deliverResult(s,s.text)}
    }
    func deliveryFinished(_ s:VoiceSession,posted:Bool){
        // Let the receiving app consume Cmd+V before capturing the new caret.
        DispatchQueue.main.asyncAfter(deadline:.now()+(posted ? 0.12 : 0)){[weak self] in
            guard let self=self else{return}
            if posted,let previous=s.pasteTarget {
                for id in self.deliveries.ids where id != s.id {
                    guard let pending=self.sessions[id],let target=pending.pasteTarget else{continue}
                    if let updated=target.followingInsertion(into:previous){pending.pasteTarget=updated}
                }
            }
            self.deliveries.finish(s.id);self.drainDeliveries()
        }
    }
    func deliverResult(_ s:VoiceSession,_ text:String){
        let settings=DeliverySettings.read(localDirectory)
        let current={ [weak s] ()->Bool in guard let s=s else{return false};return s.complete && !s.restored && s.deliveryStatus==nil}
        let complete={ [weak self,weak s] (outcome:PasteOutcome)->Void in
            guard let self=self,let s=s else{return}
            guard current() else{self.deliveryFinished(s,posted:false);return}
            var result=outcome
            if outcome != .posted && outcome != .copied && settings.keepTranscription && self.autoPaste.copy(text){result = .copied}
            s.deliveryStatus=result.message;self.lastPasteStatus=result.message;self.refresh()
            EventLog.record("delivery",phase:String(describing:outcome))
            self.deliveryFinished(s,posted:outcome == .posted)
            self.capsule.hide(after:result == .posted || result == .copied ? 0.45 : 2.5){[weak self,weak s] in guard let self=self,let s=s else{return false};return self.active==nil && self.displayed?.id==s.id}
        }
        guard current() else{deliveryFinished(s,posted:false);return}
        if settings.autoPaste,let token=s.localInputToken {
            workbench.insertInput(token:token,text:text){[weak self] ok in if ok && settings.keepTranscription{_ = self?.autoPaste.copy(text)};complete(ok ? .posted : .targetChanged)}
        } else {autoPaste.paste(text,target:s.pasteTarget,settings:settings,current:current,completion:complete)}
    }
    func capturePasteTarget()->PasteTarget? {
        PasteTarget.capture{[weak self] in guard let self=self,self.hotkey.enabled else{return nil};return self.hotkey.inputRevision}
    }
    func testPaste() {
        guard active==nil,!stoppingCapture,!sessions.values.contains(where:{!$0.complete && $0.failure==nil}) else {pasteTestStatus="请先结束录音并等待识别完成。";return}
        guard AutoPaste.authorized else {pasteTestStatus="请先允许自动粘贴权限。";return}
        pasteTestGeneration+=1;let generation=pasteTestGeneration,stopped=lastStoppedSession
        pasteTestRunning=true;pasteTestStatus="请在5秒内切到空白输入框，稍后填入测试文字。"
        DispatchQueue.main.asyncAfter(deadline:.now()+5){[weak self] in
            guard let self=self,self.pasteTestGeneration==generation,self.active==nil else{return}
            let application=NSWorkspace.shared.frontmostApplication?.localizedName ?? "未知应用"
            self.autoPaste.paste("小哈语音粘贴测试",target:self.capturePasteTarget(),current:{[weak self] in
                guard let self=self else{return false};return self.active==nil && self.pasteTestGeneration==generation && self.lastStoppedSession==stopped
            }){[weak self] outcome in
                guard let self=self,self.pasteTestGeneration==generation else{return}
                self.pasteTestRunning=false
                self.pasteTestStatus=outcome == .posted ? "已向「"+application+"」触发粘贴，请在目标输入框核对。测试不计入历史。" : outcome.message.replacingOccurrences(of:"文字已保留",with:"测试未粘贴")
            }
        }
    }
    var pendingSessions:[VoiceSession] {sessions.values.filter{!$0.complete && !$0.pcm.isEmpty}.sorted{$0.createdAt>$1.createdAt}}
    func preserve(_ session:VoiceSession){do{try recovery.save(session)}catch{historyError="未完成录音暂未保存，请保持程序运行并检查磁盘空间。"}}
    func refresh() {
        let toggleTitle=active == nil ? "开始说话" : "结束说话"
        if toggleItem?.title != toggleTitle {toggleItem?.title=toggleTitle}
        let keyTitle=(hotkey.enabled ? "暂停 " : "启用 ")+hotkey.shortcut.label
        if keyItem?.title != keyTitle {keyItem?.title=keyTitle}
        if dashboardHotkeyButton.title != keyTitle {dashboardHotkeyButton.title=keyTitle}
        if recordingIndicator != (active != nil) {
            recordingIndicator=(active != nil)
            item?.button?.image=NSImage(systemSymbolName:active != nil ? "mic.fill" : "waveform",accessibilityDescription:active != nil ? "正在录音" : "小哈语音")
        }
        var state="准备好",text="",seconds=0.0,recording=false,retryable=false
        if let s=displayed {
            text=s.text;recording=s.recording;retryable=s.failure != nil && !s.complete
            seconds=s.complete ? s.completedSeconds : s.seconds
            if s.complete {state=s.deliveryStatus ?? "已完成"}
            else if s.failure != nil {state=s.recording ? "录音继续 · 识别断开" : "文字待补全"}
            else if s.recording {state=s.bridgeReady ? "聆听中" : "录音中 · 正在连接"}
            else {state="正在整理"}
        }
        capsule.applyTheme(capsuleThemes.resolved,palette:capsuleThemes.palette)
        capsule.update(state:state,text:text,seconds:seconds,recording:recording,hotkey:hotkey.enabled,retryable:retryable,keyLabel:hotkey.shortcut.label)
        let summary=String(format:"本机  %d 次  ·  %d 字  ·  %.1f 分钟",history?.records.count ?? 0,history?.characters ?? 0,(history?.seconds ?? 0)/60)
        if stats.stringValue != summary {stats.stringValue=summary}
        var explanation:String
        if let historyError=historyError {explanation=historyError}
        else if !shortcutSafe {explanation="原输入法右 Option 需先避开冲突。可先用菜单栏开始/结束；本机保存完成的文字历史与统计，录音不落盘。"}
        else if !RightOptionMonitor.authorized {explanation="点击“启用右 Option”，并由你在系统设置中允许“小哈语音”输入监控；这项权限只用于启停；自动粘贴需另外允许辅助功能。"}
        else {explanation=hotkey.shortcut.label+" 按一次开始，再按一次结束。普通键、鼠标和切窗口继续录音；完成后按设置自动粘贴或只复制。工作台可查看本机历史、统计和账号同步。"}
        if let s=displayed,s.failure != nil {explanation="识别连接已断开，录音仍可继续；内存中保留本段音频，可点胶囊“重试识别”。退出前请完成识别。"}
        if help.stringValue != explanation {help.stringValue=explanation}
        let pasteTitle=AutoPaste.authorized ? "自动粘贴已允许" : "启用自动粘贴"
        if pastePermissionButton.title != pasteTitle {pastePermissionButton.title=pasteTitle}
        pastePermissionButton.isEnabled = !AutoPaste.authorized
    }
    @objc func showCapsule(){capsule.show()}
    func copyDisplayed() {
        guard let text=displayed?.text,!text.isEmpty else{return}
        autoPaste.clipboard.abandon()
        NSPasteboard.general.clearContents();NSPasteboard.general.setString(text,forType:.string)
    }
    @objc func showDashboard() {
        if dashboard == nil {buildDashboard()}
        refreshHistory();dashboard?.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
    }
    @objc func enablePaste(){AutoPaste.requestPermission();showDashboard()}
    func buildDashboard() {
        let w=NSWindow(contentRect:NSRect(x:0,y:0,width:700,height:470),styleMask:[.titled,.closable,.miniaturizable,.resizable],backing:.buffered,defer:false)
        w.title="小哈语音 · 本机历史与统计";w.isReleasedWhenClosed=false
        let title=NSTextField(labelWithString:"小哈语音");title.font = .systemFont(ofSize:23,weight:.semibold)
        stats.font = .systemFont(ofSize:14,weight:.medium);help.textColor = .secondaryLabelColor
        let start=NSButton(title:"开始 / 结束",target:self,action:#selector(toggle))
        dashboardHotkeyButton.target=self;dashboardHotkeyButton.action=#selector(enableHotkey)
        historyCopyButton.target=self;historyCopyButton.action=#selector(copyHistory)
        pastePermissionButton.target=self;pastePermissionButton.action=#selector(enablePaste)
        let buttons=NSStackView(views:[start,dashboardHotkeyButton,pastePermissionButton,historyCopyButton]);buttons.spacing=8
        selector.target=self;selector.action=#selector(selectHistory)
        let scroll=NSScrollView();scroll.hasVerticalScroller=true;scroll.borderType = .bezelBorder
        result.isEditable=false;result.isSelectable=true;result.font = .systemFont(ofSize:16);result.textContainerInset=NSSize(width:12,height:12);result.autoresizingMask=[.width];scroll.documentView=result
        let stack=NSStackView(views:[title,stats,help,buttons,selector,scroll]);stack.orientation = .vertical;stack.alignment = .leading;stack.spacing=14;stack.translatesAutoresizingMaskIntoConstraints=false
        w.contentView!.addSubview(stack)
        NSLayoutConstraint.activate([stack.leadingAnchor.constraint(equalTo:w.contentView!.leadingAnchor,constant:22),stack.trailingAnchor.constraint(equalTo:w.contentView!.trailingAnchor,constant:-22),stack.topAnchor.constraint(equalTo:w.contentView!.topAnchor,constant:22),stack.bottomAnchor.constraint(equalTo:w.contentView!.bottomAnchor,constant:-22),help.widthAnchor.constraint(equalTo:stack.widthAnchor),selector.widthAnchor.constraint(equalTo:stack.widthAnchor),scroll.widthAnchor.constraint(equalTo:stack.widthAnchor),scroll.heightAnchor.constraint(greaterThanOrEqualToConstant:150)])
        w.center();dashboard=w
    }
    func refreshHistory() {
        guard dashboard != nil else{return}
        let previous=selector.indexOfSelectedItem
        historyCopyButton.isEnabled = !(history?.records.isEmpty ?? true)
        selector.removeAllItems()
        let formatter=DateFormatter();formatter.dateFormat="MM-dd HH:mm"
        for r in history?.records ?? [] {selector.addItem(withTitle:formatter.string(from:r.createdAt)+"  "+String(r.text.replacingOccurrences(of:"\n",with:" ").prefix(40)))}
        if selector.numberOfItems>0 {selector.selectItem(at:min(max(previous,0),selector.numberOfItems-1));selectHistory()}
        else {selector.addItem(withTitle:"还没有完成的文字记录");result.string="说完并完成识别后，本机文字历史会显示在这里。"}
        refresh()
    }
    @objc func selectHistory() {
        let i=selector.indexOfSelectedItem
        if let records=history?.records,records.indices.contains(i) {result.string=records[i].text}
    }
    @objc func copyHistory(){guard let records=history?.records,records.indices.contains(selector.indexOfSelectedItem) else{return};autoPaste.clipboard.abandon();NSPasteboard.general.clearContents();NSPasteboard.general.setString(records[selector.indexOfSelectedItem].text,forType:.string)}
    @objc func quit(){NSApp.terminate(nil)}
    func applicationShouldTerminate(_ sender:NSApplication)->NSApplication.TerminateReply {
        if toolkit.busy{toolkit.status="备份或恢复尚未结束，请完成后再退出。";openSettings();return .terminateCancel}
        if active != nil {
            let alert=NSAlert();alert.messageText="当前仍在录音";alert.informativeText="请先用启停键结束录音，再退出。内容会继续保留。";alert.addButton(withTitle:"继续使用");alert.runModal();return .terminateCancel
        }
        do {for session in pendingSessions{try recovery.save(session)}} catch {
            let alert=NSAlert();alert.messageText="未完成录音尚未备份成功";alert.informativeText="为避免丢失音频，已取消退出。请检查可用空间后重试。";alert.addButton(withTitle:"继续使用");alert.runModal();return .terminateCancel
        }
        workbench.stop();autoPaste.cancel();hotkey.stop();recorder.stop {} ;for s in sessions.values {s.bridge?.cancel()};return .terminateNow
    }
}
let app=NSApplication.shared
let delegate=VoiceApp()
app.delegate=delegate
app.run()
