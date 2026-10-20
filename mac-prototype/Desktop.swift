import AppKit
import WebKit
import CryptoKit

// A LaunchAgent opens the app through LaunchServices, then exits. Disabling it never kills a recording.
final class LoginLaunch {
    let label="com.xiaoha.voice.login"
    let bundle:URL
    var path:URL {FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/LaunchAgents/\(label).plist")}
    init(bundle:URL=Bundle.main.bundleURL){self.bundle=bundle.resolvingSymlinksInPath()}
    var enabled:Bool {
        guard let data=try? Data(contentsOf:path),let p=(try? PropertyListSerialization.propertyList(from:data,format:nil)) as? [String:Any],p["Label"] as? String == label else{return false}
        guard var stored=p["ProgramArguments"] as? [String],stored.count==arguments.count else{return false}
        stored[4]=URL(fileURLWithPath:stored[4]).resolvingSymlinksInPath().path
        return stored==arguments
    }
    func migrateAliasIfNeeded() throws {
        guard enabled,let data=try? Data(contentsOf:path),let value=(try? PropertyListSerialization.propertyList(from:data,format:nil)) as? [String:Any],value["ProgramArguments"] as? [String] != arguments else{return}
        try set(true)
    }
    var arguments:[String] {["/usr/bin/open","-g","-j","-a",bundle.path,"--args","--login"]}
    func set(_ enabled:Bool) throws {
        if enabled {
            try FileManager.default.createDirectory(at:path.deletingLastPathComponent(),withIntermediateDirectories:true)
            if FileManager.default.fileExists(atPath:path.path) && !self.enabled {throw NSError(domain:"自动启动项与当前安装不一致，请先核对。",code:1)}
            let p:[String:Any] = ["Label":label,"ProgramArguments":arguments,"RunAtLoad":true,"LaunchOnlyOnce":true,"ProcessType":"Background"]
            let data=try PropertyListSerialization.data(fromPropertyList:p,format:.xml,options:0)
            try data.write(to:path,options:.atomic)
            try FileManager.default.setAttributes([.posixPermissions:0o600],ofItemAtPath:path.path)
            _ = command(["bootstrap","gui/\(getuid())",path.path])
        } else if FileManager.default.fileExists(atPath:path.path) {
            guard self.enabled else {throw NSError(domain:"自动启动项与当前安装不一致，未移除。",code:2)}
            _ = command(["bootout","gui/\(getuid())/\(label)"])
            try FileManager.default.removeItem(at:path)
        }
    }
    private func command(_ args:[String])->Int32 {
        let p=Process();p.executableURL=URL(fileURLWithPath:"/bin/launchctl");p.arguments=args
        p.standardOutput=FileHandle.nullDevice;p.standardError=FileHandle.nullDevice
        do {try p.run();p.waitUntilExit();return p.terminationStatus} catch{return -1}
    }
}

final class DesktopWorkbench:NSObject,NSWindowDelegate,WKNavigationDelegate,WKScriptMessageHandlerWithReply {
    let root:URL,history:URL,login=LoginLaunch()
    let origin="http://127.0.0.1:8766"
    var window:NSWindow?,web:WKWebView?,process:Process?
    var launching=false,pendingPath="/workbench",deadline=Date.distantPast
    var state:(()->[String:Any])?
    var action:((String)->Void)?
    var copyText:((String)->Void)?
    var configure:((String,[String:Any]) throws -> [String:Any])?
    var keepDock=false
    var toolkit:ToolkitManager?
    var dataDirectory:URL {RuntimePaths.companion}
    init(root:URL,history:URL){self.root=root;self.history=history}
    func show(_ path:String="/workbench") {
        guard path=="/" || path.hasPrefix("/workbench") else{return}
        pendingPath=path
        if window == nil {build()}
        NSApp.setActivationPolicy(keepDock ? .regular : .accessory);window?.makeKeyAndOrderFront(nil);NSApp.activate(ignoringOtherApps:true)
        if launching{return}
        launching=true;deadline=Date().addingTimeInterval(45)
        check()
    }
    func build() {
        let config=WKWebViewConfiguration();config.userContentController.addScriptMessageHandler(self,contentWorld:.page,name:"xiaoha")
        // Account login stays in the user's local WK data store. No remote page receives a native bridge.
        let view=WKWebView(frame:.zero,configuration:config);view.navigationDelegate=self
        let w=NSWindow(contentRect:NSRect(x:0,y:0,width:1100,height:760),styleMask:[.titled,.closable,.miniaturizable,.resizable,.fullSizeContentView],backing:.buffered,defer:false)
        w.title="小哈语音";w.minSize=NSSize(width:780,height:600);w.isReleasedWhenClosed=false;w.delegate=self
        w.titleVisibility = .hidden;w.titlebarAppearsTransparent=true;w.titlebarSeparatorStyle = .none
        w.backgroundColor=NSColor(calibratedRed:0.969,green:0.961,blue:0.949,alpha:1)
        w.contentView=WorkbenchChrome(content:view)
        w.center();(w.contentView as? WorkbenchChrome)?.trackWindowMovement();window=w;web=view
        view.loadHTMLString("<html lang='zh'><meta charset='utf-8'><body style='background:#f3f4ef;color:#263c35;font:16px -apple-system;padding:50px'>正在打开小哈语音…</body></html>",baseURL:nil)
    }
    func check() {
        var request=URLRequest(url:URL(string:origin+"/api/health")!);request.timeoutInterval=1
        URLSession.shared.dataTask(with:request) { [weak self] data,response,error in
            DispatchQueue.main.async {
                guard let self=self else{return}
                if let response=response as? HTTPURLResponse {
                    let value=data.flatMap{try? JSONSerialization.jsonObject(with:$0)} as? [String:Any]
                    let expected=SHA256.hash(data:Data(self.dataDirectory.resolvingSymlinksInPath().path.utf8)).map{String(format:"%02x",$0)}.joined()
                    guard response.statusCode==200,value?["service"] as? String == "xiaoha-voice-companion",value?["protocol"] as? Int == 3,value?["instance"] as? String == expected else {self.fail("工作台端口正被其他程序占用，未关闭或替换它。请退出冲突程序后，从菜单栏重新打开。");return}
                    self.launching=false
                    self.web?.load(URLRequest(url:URL(string:self.origin+self.pendingPath)!));return
                }
                if self.process?.isRunning != true {
                    let python=RuntimePaths.executable ?? self.root.appendingPathComponent(".venv/bin/python")
                    guard FileManager.default.isExecutableFile(atPath:python.path) else {self.fail("本机运行环境缺失，语音录音仍可使用。请恢复同步组件后重新打开。");return}
                    let p=Process();p.executableURL=python;p.currentDirectoryURL=self.root
                    p.arguments=(RuntimePaths.executable != nil ? ["control"] : ["-m","desktop.control"])+["--no-browser","--data",self.dataDirectory.path,"--history",self.history.path,"--wordbook",self.history.deletingLastPathComponent().appendingPathComponent("sync-wordbook.json").path]
                    p.environment=RuntimePaths.environment
                    p.standardOutput=FileHandle.nullDevice;p.standardError=FileHandle.nullDevice
                    do {try p.run();self.process=p} catch {self.fail("工作台未能启动，原有语音与历史没有改变。请从菜单栏重试。");return}
                }
                guard Date()<self.deadline else {self.fail("工作台启动较慢，请从菜单栏重新打开。原有语音与历史没有改变。");return}
                DispatchQueue.main.asyncAfter(deadline:.now()+0.25){[weak self] in self?.check()}
            }
        }.resume()
    }
    func fail(_ text:String) {
        launching=false
        web?.loadHTMLString("<html lang='zh'><meta charset='utf-8'><body style='background:#f3f4ef;color:#263c35;font:16px -apple-system;padding:50px'>\(text)</body></html>",baseURL:nil)
    }
    func stop(){web?.loadHTMLString("",baseURL:nil);if process?.isRunning == true {process?.terminate()};process=nil}
    func windowDidMove(_ notification:Notification){(window?.contentView as? WorkbenchChrome)?.windowMoved()}
    func windowWillClose(_ notification:Notification){NSApp.setActivationPolicy(keepDock ? .regular : .accessory)}
    func historyChanged(){web?.evaluateJavaScript("window.dispatchEvent(new Event('xiaoha-history'))",completionHandler:nil)}
    func captureInput(_ completion:@escaping(String?)->Void){
        guard window?.isKeyWindow==true,web?.url?.path=="/workbench" else{completion(nil);return}
        web?.evaluateJavaScript("window.xiaohaCaptureField?.()",completionHandler:{value,_ in completion(value as? String)})
    }
    func insertInput(token:String,text:String,completion:@escaping(Bool)->Void){
        guard window?.isKeyWindow==true,NSWorkspace.shared.frontmostApplication?.processIdentifier==ProcessInfo.processInfo.processIdentifier,let data=try? JSONSerialization.data(withJSONObject:[token,text]),let args=String(data:data,encoding:.utf8) else{completion(false);return}
        web?.evaluateJavaScript("window.xiaohaInsertField?.(...\(args))",completionHandler:{value,_ in completion(value as? Bool == true)})
    }
    func capturedMouseShortcut(_ value:[String:Any]){guard let data=try? JSONSerialization.data(withJSONObject:value),let json=String(data:data,encoding:.utf8) else{return};web?.evaluateJavaScript("window.dispatchEvent(new CustomEvent('xiaoha-mouse-shortcut',{detail:\(json)}))",completionHandler:nil)}
    func webView(_ webView:WKWebView,didFinish navigation:WKNavigation!) {
        func useOverlay(_ view:NSView) {
            if let scroll=view as? NSScrollView {scroll.scrollerStyle = .overlay;scroll.autohidesScrollers=true}
            for child in view.subviews {useOverlay(child)}
        }
        useOverlay(webView)
    }
    func webView(_ webView:WKWebView,decidePolicyFor navigationAction:WKNavigationAction,decisionHandler:@escaping(WKNavigationActionPolicy)->Void) {
        guard let url=navigationAction.request.url else{decisionHandler(.cancel);return}
        if url.scheme=="about" {decisionHandler(.allow);return}
        if url.scheme=="http",url.host=="127.0.0.1",url.port==8766 {decisionHandler(.allow);return}
        if navigationAction.navigationType == .linkActivated,["https","http"].contains(url.scheme ?? "") {NSWorkspace.shared.open(url)}
        decisionHandler(.cancel)
    }
    func userContentController(_ userContentController:WKUserContentController,didReceive message:WKScriptMessage,replyHandler:@escaping(Any?,String?)->Void) {
        guard message.frameInfo.isMainFrame,message.frameInfo.securityOrigin.protocol=="http",message.frameInfo.securityOrigin.host=="127.0.0.1",message.frameInfo.securityOrigin.port==8766,web?.url?.path=="/workbench",let body=message.body as? [String:Any],let command=body["action"] as? String else {replyHandler(nil,"此操作只能从本机工作台发起");return}
        switch command {
        case "backupToolkit":toolkit?.backup(reply:replyHandler)
        case "chooseRestore":toolkit?.chooseRestore(reply:replyHandler)
        case "restoreToolkit":toolkit?.restore(body["value"] as? [String:Any] ?? [:],reply:replyHandler)
        case "status":var value=state?() ?? [:];value["launch_at_login"]=login.enabled;replyHandler(value,nil)
        case "launchAtLogin":
            guard let enabled=body["value"] as? Bool else {replyHandler(nil,"启动设置无效");return}
            do {try login.set(enabled);replyHandler(["ok":true],nil)} catch {replyHandler(nil,"自动启动暂未更改，请检查登录项设置。")}
        case "startup","shortcut","beginShortcut","cancelShortcut","recovery","retryRecovery","discardRecovery","capsuleAppearance":
            do {replyHandler(try configure?(command,body["value"] as? [String:Any] ?? [:]) ?? ["ok":false],nil)} catch {replyHandler(nil,error.localizedDescription)}
        case "inputPermission","pastePermission","microphoneSettings","pasteTest","previewCapsule":action?(command);replyHandler(["ok":true],nil)
        case "copy":
            guard let text=body["value"] as? String,text.utf8.count<=1_000_000 else {replyHandler(nil,"复制内容过大");return}
            copyText?(text);replyHandler(["ok":true],nil)
        case "export":
            guard let v=body["value"] as? [String:Any],let text=v["text"] as? String,text.utf8.count<=50_000_000 else {replyHandler(nil,"导出内容过大");return}
            let panel=NSSavePanel();panel.title="导出文件";let name=v["filename"] as? String ?? "小哈语音-本机历史.txt";panel.nameFieldStringValue=name.contains("/") || name.count>100 ? "小哈语音-导出.txt" : name
            guard let window=window else {replyHandler(nil,"请先打开工作台");return}
            panel.beginSheetModal(for:window){result in
                if result == .OK,let url=panel.url {do {try text.write(to:url,atomically:true,encoding:.utf8);replyHandler(["ok":true],nil)}catch{replyHandler(nil,"文件保存失败，原历史没有改变")}}
                else {replyHandler(["cancelled":true],nil)}
            }
        default:replyHandler(nil,"不支持的本机操作")
        }
    }
}
