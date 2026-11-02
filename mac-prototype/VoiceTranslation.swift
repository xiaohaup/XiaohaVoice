import Foundation
import CryptoKit

struct VoiceEnglishConfiguration:Decodable {
    var enabled:Bool
    var endpoint:String
    var model:String
    var credential_saved:Bool
    var revision:String
    var shortcut:VoiceShortcut
    static func read(_ directory:URL)->VoiceEnglishConfiguration? {
        guard let bytes=try? Data(contentsOf:directory.appendingPathComponent("translation-settings.json")),bytes.count<32768,
              let value=try? JSONDecoder().decode(Self.self,from:bytes),value.enabled,value.credential_saved,
              !value.revision.isEmpty,!value.endpoint.isEmpty,!value.model.isEmpty,value.shortcut.valid else{return nil}
        return value
    }
    var panelShortcut:PanelShortcut {PanelShortcut(enabled:true,keyCode:shortcut.keyCode,modifiers:shortcut.modifiers,label:shortcut.label,mouseButton:shortcut.mouseButton,mode:"single")}
}

protocol VoiceTranslationLease:AnyObject {func cancel()}
struct VoiceEnglishResponse {let text:String;let milliseconds:Int}
protocol VoiceTextTranslating {
    func translate(_ text:String,revision:String,completion:@escaping(Result<VoiceEnglishResponse,Error>)->Void)->VoiceTranslationLease
}

/// One final corrected source, one generation. Normal output never creates this.
final class VoiceEnglishOutput {
    enum Phase {case waiting,translating,ready,failed,cancelled}
    let source:String,revision:String
    private(set) var phase=Phase.waiting
    private(set) var text:String?,error:String?,milliseconds:Int?
    private var generation=0,lease:VoiceTranslationLease?
    var pending:Bool {phase == .waiting || phase == .translating}
    init(source:String,revision:String){self.source=source;self.revision=revision}
    func start(using provider:VoiceTextTranslating,changed:@escaping()->Void){
        generation+=1;let epoch=generation;lease?.cancel();lease=nil;phase = .translating;text=nil;error=nil
        let next=provider.translate(source,revision:revision){[weak self] result in
            guard let self=self,self.generation==epoch,self.phase == .translating else{return}
            self.lease=nil
            switch result {
            case .success(let value):
                guard !value.text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty,value.text.utf8.count<=50000 else{self.phase = .failed;self.error="翻译没有返回有效文字，中文原稿已保留";changed();return}
                self.phase = .ready;self.text=value.text;self.milliseconds=value.milliseconds
            case .failure(let error):self.phase = .failed;self.error=error.localizedDescription
            }
            changed()
        }
        if generation==epoch && phase == .translating{lease=next}else{next.cancel()}
    }
    func cancel(){generation+=1;lease?.cancel();lease=nil;phase = .cancelled;text=nil;error=nil}
    deinit{lease?.cancel()}
}

struct NativeVoiceTextTranslator:VoiceTextTranslating {
    var configuration:URLSessionConfiguration?=nil
    var directory:URL?=nil
    var origin:URL?=nil
    func translate(_ text:String,revision:String,completion:@escaping(Result<VoiceEnglishResponse,Error>)->Void)->VoiceTranslationLease {
        let task=VoiceTranslationRequest(configuration:configuration ?? .ephemeral,directory:directory ?? RuntimePaths.companion,origin:origin ?? RuntimePaths.origin,completion:completion)
        task.start(text:text,revision:revision)
        return task
    }
}

/// The already-running local owner holds the Key. Native requests never fetch,
/// receive or persist it, and do not create a new credential reader per utterance.
private final class VoiceTranslationRequest:NSObject,VoiceTranslationLease,URLSessionTaskDelegate,@unchecked Sendable {
    private let lock=NSLock(),directory:URL,origin:URL
    private var session:URLSession!,running:Task<Void,Never>?
    private var live=true,completion:((Result<VoiceEnglishResponse,Error>)->Void)?
    init(configuration:URLSessionConfiguration,directory:URL,origin:URL,completion:@escaping(Result<VoiceEnglishResponse,Error>)->Void){
        self.directory=directory;self.origin=origin;self.completion=completion;super.init()
        let config=configuration.copy() as! URLSessionConfiguration
        config.httpCookieStorage=nil;config.urlCache=nil;config.httpShouldSetCookies=false
        config.requestCachePolicy = .reloadIgnoringLocalCacheData
        config.timeoutIntervalForRequest=24;config.timeoutIntervalForResource=25
        config.connectionProxyDictionary=[:]
        session=URLSession(configuration:config,delegate:self,delegateQueue:nil)
    }
    private static func failure(_ text:String)->NSError{NSError(domain:"VoiceEnglish",code:1,userInfo:[NSLocalizedDescriptionKey:text])}
    func start(text:String,revision:String){
        lock.lock();guard live else{lock.unlock();return}
        running=Task(priority:.userInitiated){ [self] in
            do {
                guard !text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty,text.utf8.count<=50000 else{throw Self.failure("翻译内容为空或过长，中文原稿已保留")}
                guard origin.scheme=="http",origin.host=="127.0.0.1",origin.port != nil,origin.user==nil,origin.password==nil,origin.query==nil,origin.fragment==nil,origin.path.isEmpty || origin.path=="/" else{throw Self.failure("本机翻译服务地址无效")}
                let (health,_)=try await fetch("/api/health")
                let service=(try? JSONSerialization.jsonObject(with:health)) as? [String:Any]
                let expected=SHA256.hash(data:Data(directory.resolvingSymlinksInPath().path.utf8)).map{String(format:"%02x",$0)}.joined()
                guard service?["service"] as? String=="xiaoha-voice-companion",service?["protocol"] as? Int==3,service?["instance"] as? String==expected else{throw Self.failure("本机翻译服务身份不匹配，原文已保留")}
                let (_,bootstrap)=try await fetch("/workbench")
                var headers=[String:String]();for (key,value) in bootstrap.allHeaderFields{headers[String(describing:key)]=String(describing:value)}
                guard let cookie=HTTPCookie.cookies(withResponseHeaderFields:headers,for:origin).first(where:{$0.name=="xh_workbench"}),validHeader(cookie.value) else{throw Self.failure("本机翻译服务尚未就绪，请重新打开小哈语音")}
                let authorization="xh_workbench="+cookie.value
                let (status,_)=try await fetch("/workbench/api/status",cookie:authorization)
                let state=(try? JSONSerialization.jsonObject(with:status)) as? [String:Any]
                guard let csrf=state?["csrf"] as? String,validHeader(csrf) else{throw Self.failure("本机翻译会话未就绪，原文已保留")}
                let payload=try JSONSerialization.data(withJSONObject:["text":text,"revision":revision])
                let (data,_)=try await fetch("/workbench/api/translation-run",body:payload,cookie:authorization,csrf:csrf)
                guard let value=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any] else{throw Self.failure("翻译组件没有返回有效结果，中文原稿已保留")}
                guard value["ok"] as? Bool == true,let translated=value["text"] as? String,!translated.isEmpty else{throw Self.failure(value["error"] as? String ?? "翻译未完成，中文原稿已保留")}
                guard translated.utf8.count<=50000 else{throw Self.failure("翻译返回内容过大，中文原稿已保留")}
                finish(.success(VoiceEnglishResponse(text:translated,milliseconds:value["milliseconds"] as? Int ?? 0)))
            }catch{finish(.failure(error is URLError ? Self.failure("本机翻译组件暂不可用或已取消，中文原稿已保留"):error))}
        }
        lock.unlock()
        DispatchQueue.main.asyncAfter(deadline:.now()+25){[weak self] in self?.finish(.failure(Self.failure("英文翻译超时，中文原稿已保留，可重试")))}
    }
    private func validHeader(_ value:String)->Bool{!value.isEmpty && value.utf8.count<=200 && value.unicodeScalars.allSatisfy{$0.value>32 && $0.value<127 && $0.value != 59}}
    private func fetch(_ path:String,body:Data?=nil,cookie:String?=nil,csrf:String?=nil) async throws -> (Data,HTTPURLResponse){
        try Task.checkCancellation()
        var request=URLRequest(url:origin.appendingPathComponent(path))
        if let cookie=cookie{request.setValue(cookie,forHTTPHeaderField:"Cookie")}
        if let body=body{request.httpMethod="POST";request.httpBody=body;request.setValue(origin.absoluteString,forHTTPHeaderField:"Origin");request.setValue("application/json",forHTTPHeaderField:"Content-Type");request.setValue(csrf,forHTTPHeaderField:"X-CSRF-Token")}
        let (data,response)=try await session.data(for:request)
        guard let http=response as? HTTPURLResponse,http.url?.scheme=="http",http.url?.host=="127.0.0.1",http.url?.port==origin.port,http.statusCode==200 else{throw Self.failure("本机翻译会话已失效，原文已保留，请重试")}
        guard data.count<=310000 else{throw Self.failure("翻译返回内容过大，中文原稿已保留")}
        return (data,http)
    }
    func urlSession(_ session:URLSession,task:URLSessionTask,willPerformHTTPRedirection response:HTTPURLResponse,newRequest request:URLRequest,completionHandler:@escaping(URLRequest?)->Void){completionHandler(nil)}
    private func finish(_ result:Result<VoiceEnglishResponse,Error>){
        lock.lock();guard live else{lock.unlock();return};live=false;let callback=completion;completion=nil
        let work=running;running=nil;lock.unlock();work?.cancel();session.invalidateAndCancel()
        DispatchQueue.main.async{callback?(result)}
    }
    func cancel(){lock.lock();live=false;completion=nil;let work=running;running=nil;lock.unlock();work?.cancel();session.invalidateAndCancel()}
}
