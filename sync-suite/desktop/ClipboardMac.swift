import AppKit
import Foundation
let board=NSPasteboard.general
let mode=CommandLine.arguments.dropFirst().first ?? ""
if mode == "read" {
    let value:[String:Any]=["revision":board.changeCount,"text":board.string(forType:.string) as Any? ?? NSNull()]
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject:value))
} else if mode == "write" {
    let data=FileHandle.standardInput.readDataToEndOfFile()
    let value=try JSONSerialization.jsonObject(with:data) as! [String:Any]
    var done=false
    if let expected=value["expected"] as? Int,let text=value["text"] as? String,board.changeCount==expected {
        board.clearContents();done=board.setString(text,forType:.string)
    }
    FileHandle.standardOutput.write(try JSONSerialization.data(withJSONObject:["written":done]))
} else {exit(2)}
