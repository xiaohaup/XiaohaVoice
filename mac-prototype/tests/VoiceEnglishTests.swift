import AppKit
import ApplicationServices
import CryptoKit

final class TranslationFixtureProtocol:URLProtocol {
    static var handler:((URLRequest)->(Int,[String:String],Data))!
    static var delay:TimeInterval=0
    private var stopped=false
    override class func canInit(with request:URLRequest)->Bool{request.url?.host=="127.0.0.1"}
    override class func canonicalRequest(for request:URLRequest)->URLRequest{request}
    override func startLoading(){
        if Self.delay>0{Thread.sleep(forTimeInterval:Self.delay)}
        guard !stopped else{return}
        let (status,headers,data)=Self.handler(request)
        let response=HTTPURLResponse(url:request.url!,statusCode:status,httpVersion:"HTTP/1.1",headerFields:headers)!
        client?.urlProtocol(self,didReceive:response,cacheStoragePolicy:.notAllowed)
        client?.urlProtocol(self,didLoad:data);client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading(){stopped=true}
}

enum AutoPaste {static let eventMarker:Int64=123456789}
final class PasteTarget {}
final class SpeechBridge {func cancel(){}}
enum RuntimePaths {
    static let origin=URL(string:"http://127.0.0.1:18766")!
    static var companion:URL{URL(fileURLWithPath:"/nonexistent-fixture-data/desktop")}
    static var executable:URL?{nil}
    static var engine:URL{URL(fileURLWithPath:"/nonexistent-fixture-engine")}
    static var workbench:URL{engine}
    static var environment:[String:String]{[:]}
}
final class TestLease:VoiceTranslationLease {var cancelled=0;func cancel(){cancelled+=1}}
final class TestTranslator:VoiceTextTranslating {
    var requests=[String](),revisions=[String](),callbacks=[(Result<VoiceEnglishResponse,Error>)->Void](),leases=[TestLease]()
    var immediate:String?
    func translate(_ text:String,revision:String,completion:@escaping(Result<VoiceEnglishResponse,Error>)->Void)->VoiceTranslationLease {
        requests.append(text);revisions.append(revision);callbacks.append(completion);let lease=TestLease();leases.append(lease)
        if let value=immediate{completion(.success(VoiceEnglishResponse(text:value,milliseconds:9)))}
        return lease
    }
    func succeed(_ i:Int,_ text:String){callbacks[i](.success(VoiceEnglishResponse(text:text,milliseconds:42)))}
    func fail(_ i:Int){callbacks[i](.failure(NSError(domain:"fixture",code:1,userInfo:[NSLocalizedDescriptionKey:"synthetic API timeout"])))}
}
@main struct VoiceEnglishTests {
 static func main()throws {
    var checks=[String]()
    func check(_ yes:@autoclosure()->Bool,_ text:String)throws{if !yes(){throw NSError(domain:text,code:1)};checks.append(text)}
    let provider=TestTranslator(),source="明天和 Claude 开会。"
    let english=VoiceEnglishOutput(source:source,revision:"saved-r1");var changes=0
    english.start(using:provider){changes+=1}
    try check(english.pending && provider.requests==[source],"only corrected final text enters translation once")
    try check(provider.revisions==["saved-r1"],"request pins saved endpoint version")
    provider.succeed(0,"Meet Claude tomorrow.")
    try check(!english.pending && english.text=="Meet Claude tomorrow." && english.milliseconds==42 && changes==1,"successful output and timing")
    provider.fail(0);try check(english.phase == .ready && changes==1,"duplicate callback cannot change completed text")
    let failed=VoiceEnglishOutput(source:source,revision:"r");failed.start(using:provider){changes+=1};provider.fail(1)
    try check(failed.phase == .failed && failed.source==source && failed.text==nil,"API failure retains corrected source and no fake English")
    failed.start(using:provider){changes+=1};provider.succeed(1,"stale previous success")
    try check(failed.pending && failed.text==nil,"retry ignores previous-generation completion")
    provider.succeed(2,"Retried English.");try check(failed.text=="Retried English.","retry reuses source without ASR")
    let cancel=VoiceEnglishOutput(source:source,revision:"r");cancel.start(using:provider){changes+=1};let before=changes;cancel.cancel();provider.succeed(3,"too late")
    try check(cancel.phase == .cancelled && cancel.text==nil && changes==before && provider.leases[3].cancelled==1,"cancel blocks late translation and callback")
    let empty=VoiceEnglishOutput(source:source,revision:"r");empty.start(using:provider){};provider.succeed(4,"   ")
    try check(empty.phase == .failed && empty.text==nil,"empty translation cannot deliver source as English")
    let sync=TestTranslator();sync.immediate="Synchronous result.";let syncOutput=VoiceEnglishOutput(source:source,revision:"r");syncOutput.start(using:sync){}
    try check(syncOutput.phase == .ready && sync.leases[0].cancelled==1,"synchronous result cleans returned lease")

    let original=VoiceSession();original.append(Data(repeating:0,count:32000));original.requestStop();original.captureDidEnd();original.finish(source)
    try check(!original.translationPending && original.outputText==source && original.complete,"ordinary Option path has no translation wait or request")
    let session=VoiceSession();session.englishRevision="r";session.append(Data(repeating:0,count:64000));session.requestStop();session.captureDidEnd()
    try check(session.translationPending && !session.complete,"English stop waits for ASR final, not partial text")
    session.connectionFailed("synthetic ASR failure");try check(!session.translationPending,"failed ASR is recoverable audio, not an endless translation job");session.beginRetry()
    session.finish(source);let pending=VoiceEnglishOutput(source:session.text,revision:"r");session.englishOutput=pending;pending.start(using:provider){}
    var queue=OrderedDeliveries();queue.append(session.id);queue.append(original.id)
    let sessions=[session.id:session,original.id:original]
    func next()->UUID?{queue.begin(ready:{let v=sessions[$0]!;return v.complete && !v.translationPending},skip:{sessions[$0]?.deliveryStatus != nil})}
    try check(next()==nil,"faster later original cannot overtake pending English")
    provider.succeed(5,"Meet Claude tomorrow.");try check(next()==session.id && session.outputText=="Meet Claude tomorrow.","English final delivered first with translated text")
    queue.finish(session.id);try check(next()==original.id,"next original remains ordered")
    let cancelledSession=VoiceSession();cancelledSession.englishRevision="r";cancelledSession.englishOutput=VoiceEnglishOutput(source:source,revision:"r");cancelledSession.cancel()
    try check(!cancelledSession.translationPending && cancelledSession.complete,"recording cancel clears English pending state")

    let fixture=URL(fileURLWithPath:CommandLine.arguments[1]);try FileManager.default.createDirectory(at:fixture,withIntermediateDirectories:true)
    let history=try HistoryStore(directory:fixture);let id=UUID();try history.append(VoiceRecord(id:id,createdAt:Date(),text:source,seconds:2));let count=history.characters
    try history.associateEnglish(id,"Meet Claude tomorrow.");try history.append(VoiceRecord(id:id,createdAt:Date(),text:"duplicate",seconds:2))
    let loaded=try HistoryStore(directory:fixture)
    try check(loaded.records.count==1 && loaded.records[0].text==source && loaded.records[0].english=="Meet Claude tomorrow.","history retains both texts without a duplicate record")
    try check(loaded.characters==count && loaded.seconds==2,"translation does not double count characters or duration")

    let monitor=RightOptionMonitor();var eligible=true,stops=0,toggles=0
    monitor.englishShortcut=PanelShortcut(enabled:true,keyCode:54,modifiers:0,label:"右 Command",mode:"single")
    monitor.shouldStopEnglish={eligible};monitor.onStopEnglish={stops+=1};monitor.onToggle={toggles+=1}
    func event(_ type:CGEventType,_ key:Int=54,_ flags:UInt64=0)->CGEvent{let e=CGEvent(source:nil)!;e.type=type;e.setIntegerValueField(.keyboardEventKeycode,value:Int64(key));e.flags=CGEventFlags(rawValue:flags);return e}
    func send(_ type:CGEventType,_ key:Int=54,_ flags:UInt64=0){_ = monitor.handle(type,event(type,key,flags))}
    func drain(){RunLoop.current.run(until:Date().addingTimeInterval(0.03))}
    send(.flagsChanged,54,0x100010);try check(stops==0,"Command down alone never ends early");send(.flagsChanged);drain();try check(stops==1 && toggles==0,"right Command release selects English only")
    send(.flagsChanged,55,0x100008);send(.flagsChanged,55,0);drain();try check(stops==1,"left Command does not end configured right Command")
    for key in [8,9,0]{send(.flagsChanged,54,0x100010);send(.keyDown,key,0x100010);send(.keyUp,key,0x100010);send(.flagsChanged);drain();try check(stops==1,"Command chord stays normal: \(key)")}
    send(.flagsChanged,54,0x100010);send(.leftMouseDown);send(.leftMouseUp);send(.flagsChanged);drain();try check(stops==1,"Command mouse operation does not stop recording")
    eligible=false;send(.flagsChanged,54,0x100010);send(.flagsChanged);drain();try check(stops==1,"idle Command cannot start recording or translation")
    eligible=true;send(.flagsChanged,61,0x80040);send(.flagsChanged,61,0);drain();try check(toggles==1 && stops==1,"original right Option remains independent")
    monitor.suspended=true;send(.flagsChanged,54,0x100010);send(.flagsChanged);drain();try check(stops==1,"shortcut capture suspends translation activation")
    monitor.suspended=false;monitor.englishShortcut=PanelShortcut(enabled:true,keyCode:100,modifiers:0,label:"F8",mode:"single");send(.keyDown,100);send(.keyUp,100);drain();try check(stops==2 && toggles==1,"custom translation finish key works without changing voice key")
    send(.flagsChanged,61,0x80040);send(.keyDown,0,0x80040);send(.keyUp,0,0x80040);send(.flagsChanged,61,0);drain()
    try check(toggles==1 && stops==2,"unrelated Option chord does not stop original or English capture")
    monitor.englishShortcut=PanelShortcut(enabled:true,keyCode:54,modifiers:0,label:"右 Command",mode:"single")
    send(.flagsChanged,54,0x100010);Thread.sleep(forTimeInterval:0.7);send(.flagsChanged);drain();try check(stops==2,"long-held Command is not a short translation tap")

    // The actual native provider is exercised with an injected URLProtocol.
    // It must authenticate to the long-lived local owner, never use a Key or
    // launch a process, and stop before posting text to an unrelated service.
    func localRequest(_ mode:String,text:String="最终纠正的 Claude。",cancel:Bool=false)->(Result<VoiceEnglishResponse,Error>?,[URLRequest]){
        var requests=[URLRequest](),result:Result<VoiceEnglishResponse,Error>?
        let directory=URL(fileURLWithPath:"/synthetic-local-owner")
        let instance=SHA256.hash(data:Data(directory.path.utf8)).map{String(format:"%02x",$0)}.joined()
        TranslationFixtureProtocol.delay=cancel ? 0.15 : 0
        TranslationFixtureProtocol.handler={request in
            requests.append(request)
            let path=request.url!.path
            if path=="/api/health"{return (200,[:],try! JSONSerialization.data(withJSONObject:["service":"xiaoha-voice-companion","protocol":3,"instance":mode=="wrong-owner" ? "wrong" : instance]))}
            if path=="/workbench"{return (200,mode=="missing-cookie" ? [:]:["Set-Cookie":"xh_workbench=fixture-cookie; Path=/workbench; HttpOnly; SameSite=Strict"],Data("fixture".utf8))}
            if path=="/workbench/api/status"{return (200,[:],Data("{\"csrf\":\"fixture-csrf\"}".utf8))}
            if mode=="expired"{return (403,[:],Data())}
            if mode=="failure"{return (200,[:],Data("{\"ok\":false,\"error\":\"测试：原文已保留\"}".utf8))}
            return (200,[:],Data("{\"ok\":true,\"text\":\"Final Claude text.\",\"milliseconds\":12}".utf8))
        }
        let config=URLSessionConfiguration.ephemeral;config.protocolClasses=[TranslationFixtureProtocol.self]
        let lease=NativeVoiceTextTranslator(configuration:config,directory:directory).translate(text,revision:"fixture-r1"){result=$0}
        if cancel{lease.cancel()}
        let deadline=Date().addingTimeInterval(cancel ? 0.25 : 3)
        while result==nil && Date()<deadline{RunLoop.current.run(until:Date().addingTimeInterval(0.01))}
        withExtendedLifetime(lease){}
        return (result,requests)
    }
    let nativeSuccess=localRequest("success")
    if case .success(let value)=nativeSuccess.0{try check(value.text=="Final Claude text." && value.milliseconds==12,"native provider returns local owner translation")}else{try check(false,"native provider returns local owner translation")}
    try check(nativeSuccess.1.map{$0.url!.path}==["/api/health","/workbench","/workbench/api/status","/workbench/api/translation-run"],"native provider uses authenticated local owner instead of a fresh worker")
    let posted=nativeSuccess.1.last!
    var postedData=posted.httpBody ?? Data()
    if postedData.isEmpty,let stream=posted.httpBodyStream{stream.open();defer{stream.close()};var buffer=[UInt8](repeating:0,count:1024);while stream.hasBytesAvailable{let n=stream.read(&buffer,maxLength:buffer.count);if n<=0{break};postedData.append(contentsOf:buffer.prefix(n))}}
    let postedObject=try JSONSerialization.jsonObject(with:postedData) as! [String:String]
    try check(posted.httpMethod=="POST" && posted.value(forHTTPHeaderField:"Cookie")=="xh_workbench=fixture-cookie" && posted.value(forHTTPHeaderField:"X-CSRF-Token")=="fixture-csrf" && posted.value(forHTTPHeaderField:"Origin")=="http://127.0.0.1:18766","native text request carries local session and CSRF")
    try check(Set(postedObject.keys)==Set(["text","revision"]) && postedObject["text"]=="最终纠正的 Claude。" && nativeSuccess.1.allSatisfy{$0.value(forHTTPHeaderField:"Authorization")==nil},"native client never receives or forwards the API Key")
    let wrong=localRequest("wrong-owner");try check(wrong.1.count==1 && wrong.0 != nil,"wrong owner rejected before text or local cookie exchange")
    let missing=localRequest("missing-cookie");try check(missing.1.count==2 && missing.0 != nil,"missing local cookie cannot post text")
    let localFailed=localRequest("failure");if case .failure(let error)=localFailed.0{try check(error.localizedDescription.contains("原文已保留"),"owner failure does not fall back to original text")}else{try check(false,"owner failure does not fall back to original text")}
    let expired=localRequest("expired");if case .failure=expired.0{try check(true,"expired local authorization fails without retries")}else{try check(false,"expired local authorization fails without retries")}
    let localEmpty=localRequest("success",text:"");try check(localEmpty.1.isEmpty && localEmpty.0 != nil,"empty text cannot invoke local or remote translation")
    let abandoned=localRequest("success",cancel:true);try check(abandoned.0==nil && !abandoned.1.contains(where:{$0.url!.path=="/workbench/api/translation-run"}),"cancel suppresses callback and text submission")
    let out:[String:Any]=["passed":true,"count":checks.count,"checks":checks,"physicalKeysPosted":false,"microphoneOpened":false,"clipboardAccessed":false,"externalNetwork":false]
    try JSONSerialization.data(withJSONObject:out,options:[.prettyPrinted,.sortedKeys]).write(to:fixture.appendingPathComponent("native-checks.json"));print("Voice English: \(checks.count) checks passed")
 }
}
