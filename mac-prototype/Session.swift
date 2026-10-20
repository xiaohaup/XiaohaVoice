import Foundation

// Capture reserves a position on stop; network completion order cannot reorder it.
struct OrderedDeliveries {
    private(set) var ids=[UUID]()
    private(set) var busy=false
    mutating func append(_ id:UUID){if !ids.contains(id){ids.append(id)}}
    mutating func begin(ready:(UUID)->Bool,skip:(UUID)->Bool)->UUID? {
        guard !busy else{return nil}
        while let id=ids.first {
            if skip(id){ids.removeFirst();continue}
            guard ready(id) else{return nil}
            busy=true;return id
        }
        return nil
    }
    mutating func finish(_ id:UUID){ids.removeAll{$0==id};busy=false}
}

// An energy check, not a speech detector. Never used to interrupt capture.
struct AudioActivity {
    private var energy=0.0,samples=0,run=0,activeFrames=0,longestRun=0,strongRun=0,longestStrongRun=0
    mutating func append(_ data:Data){
        data.withUnsafeBytes { raw in
            for sample in raw.bindMemory(to:Int16.self){
                let value=Double(Int16(littleEndian:sample))/32768
                energy+=value*value;samples+=1
                if samples==320 {
                    let rms=sqrt(energy/320)
                    if rms>=0.002 {run+=1;activeFrames+=1;longestRun=max(longestRun,run)}else{run=0}
                    if rms>=0.006 {strongRun+=1;longestStrongRun=max(longestStrongRun,strongRun)}else{strongRun=0}
                    energy=0;samples=0
                }
            }
        }
    }
    var hasSustainedSignal:Bool {longestRun>=5 || activeFrames>=12 || longestStrongRun>=2}
}

enum RecognitionEnding {case empty,failed}
enum UnfinishedDisposition {case waitForStop,closeQuietly,retain}

final class VoiceSession {
    var applicationName:String?
    let id:UUID
    let createdAt:Date
    init(id:UUID=UUID(),createdAt:Date=Date()){self.id=id;self.createdAt=createdAt}
    var pcm = Data()
    private(set) var activity=AudioActivity()
    var restored=false
    var hasText:Bool {!text.trimmingCharacters(in:.whitespacesAndNewlines).isEmpty}
    var canCloseEmptyResult:Bool {captureEnded && !hasText && !activity.hasSustainedSignal && !restored}
    func unfinishedDisposition(_ ending:RecognitionEnding)->UnfinishedDisposition {
        guard captureEnded else{return .waitForStop}
        guard !complete,!restored,!hasText,!activity.hasSustainedSignal else{return .retain}
        // A failed connection is not proof of silence. Only a brief, weak,
        // new capture may be treated as an accidental tap on this path.
        return ending == .empty || seconds<=1.0 ? .closeQuietly : .retain
    }
    var text = ""
    private(set) var recording = true
    private(set) var captureEnded = false
    private(set) var complete = false
    var bridgeReady = false
    var sentOffset = 0
    var stopSent = false
    var generation = 0
    var failure: String?
    var bridge: SpeechBridge?
    var pasteTarget:PasteTarget?
    var localInputToken:String?
    var targetReady=true
    var whenTargetReady:(()->Void)?
    var deliveryStatus:String?
    var seconds: Double { Double(pcm.count) / 32000 }
    var completedSeconds: Double = 0
    func append(_ data: Data) { if !captureEnded { pcm.append(data);activity.append(data) } }
    func requestStop() { recording = false }
    func captureDidEnd() { captureEnded = true }
    func connectionFailed(_ message:String) { bridgeReady=false;failure=message }
    func beginRetry() { generation += 1;bridgeReady=false;sentOffset=0;stopSent=false;failure=nil }
    func cancel(){generation+=1;recording=false;captureEnded=true;complete=true;completedSeconds=seconds;bridgeReady=false;failure=nil;text="";pasteTarget=nil;pcm.removeAll()}
    func finish(_ result:String) { text=result;completedSeconds=seconds;complete=true;bridgeReady=false;failure=nil;pcm.removeAll() }
}
