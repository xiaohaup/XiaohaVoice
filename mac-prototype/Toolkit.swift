import AppKit

final class ToolkitManager {
    weak var workbench:DesktopWorkbench?
    var prepare:(() throws -> Void)?
    var restored:(() throws -> Void)?
    var busy=false,status=""
    private var restoreURL:URL?,restoreToken:String?,expires=Date.distantPast
    init(workbench:DesktopWorkbench){self.workbench=workbench}
    private func run(_ arguments:[String],completion:@escaping([String:Any]?,String?)->Void){
        guard let executable=RuntimePaths.executable else{completion(nil,"请从完整工具包打开这个功能");return}
        DispatchQueue.global(qos:.utility).async {
            let p=Process(),pipe=Pipe();p.executableURL=executable;p.arguments=arguments;p.environment=RuntimePaths.environment;p.standardOutput=pipe;p.standardError=FileHandle.nullDevice
            do {
                try p.run();let data=pipe.fileHandleForReading.readDataToEndOfFile();p.waitUntilExit()
                let value=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any]
                DispatchQueue.main.async{completion(p.terminationStatus==0 ? value : nil,value?["error"] as? String ?? (p.terminationStatus==0 ? nil : "操作未完成，原资料已保留"))}
            } catch {DispatchQueue.main.async{completion(nil,"工具包运行组件未能启动，原资料已保留")}}
        }
    }
    func backup(reply:@escaping(Any?,String?)->Void){
        guard !busy,let window=workbench?.window,let toolkit=RuntimePaths.toolkit else{reply(nil,"请从完整工具包打开，或等待当前操作完成");return}
        let panel=NSSavePanel();panel.title="完整备份小哈语音";let f=DateFormatter();f.dateFormat="yyyyMMdd-HHmmss";panel.nameFieldStringValue="小哈语音-完整备份-\(f.string(from:Date())).zip"
        panel.beginSheetModal(for:window){[weak self] result in
            guard let self=self else{return};guard result == .OK,let url=panel.url else{reply(["cancelled":true],nil);return}
            do{try self.prepare?()}catch{reply(nil,error.localizedDescription);return}
            self.busy=true;self.status="正在创建完整备份…";reply(["started":true],nil)
            self.run(["backup","--toolkit",toolkit.path,"--output",url.path]){value,error in self.busy=false;self.status=error ?? "完整备份已保存，含 \(value?["records"] as? Int ?? 0) 条完成记录。";EventLog.record("backup",phase:error == nil ? "done" : "error")}
        }
    }
    func chooseRestore(reply:@escaping(Any?,String?)->Void){
        guard !busy,let window=workbench?.window else{reply(nil,"请等待当前操作完成");return}
        let panel=NSOpenPanel();panel.title="选择小哈语音完整备份";panel.canChooseDirectories=false;panel.allowsMultipleSelection=false
        panel.beginSheetModal(for:window){[weak self] result in
            guard let self=self else{return};guard result == .OK,let url=panel.url else{reply(["cancelled":true],nil);return}
            self.busy=true;self.status="正在校验备份，原资料未改动…"
            self.run(["inspect","--archive",url.path]){value,error in
                self.busy=false;self.status=error ?? "备份校验通过，等待你确认恢复。"
                guard var value=value else{reply(nil,error);return}
                let token=UUID().uuidString;self.restoreURL=url;self.restoreToken=token;self.expires=Date().addingTimeInterval(300);value["token"]=token;reply(value,nil)
            }
        }
    }
    func restore(_ value:[String:Any],reply:@escaping(Any?,String?)->Void){
        guard !busy,let token=value["token"] as? String,token==restoreToken,Date()<expires,let url=restoreURL else{reply(nil,"备份选择已失效，请重新选择");return}
        do{try prepare?()}catch{reply(nil,error.localizedDescription);return}
        busy=true;status="正在合并恢复，当前新记录会保留…";restoreToken=nil;reply(["started":true],nil)
        let previousProcess=workbench?.process;workbench?.stop()
        DispatchQueue.global(qos:.utility).async{[weak self] in
            previousProcess?.waitUntilExit()
            DispatchQueue.main.async{[weak self] in
                guard let self=self else{return}
                self.run(["restore-data","--archive",url.path,"--data",RuntimePaths.data.path]){result,error in
                    self.busy=false;self.status=error ?? "恢复完成，历史已合并；恢复前资料仍有保留副本。"
                    if error==nil{do{try self.restored?()}catch{self.status="资料已恢复，请重新打开小哈语音以重新载入历史"}}
                    EventLog.record("restore",phase:error == nil ? "done" : "error");self.workbench?.show("/workbench#app")
                }
            }
        }
    }
}
