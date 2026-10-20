import Foundation

// A regular Finder alias keeps its icon metadata outside the signed app bundle.
guard CommandLine.arguments.count==3 else{exit(2)}
let destination=URL(fileURLWithPath:CommandLine.arguments[1])
let alias=URL(fileURLWithPath:CommandLine.arguments[2])
guard !FileManager.default.fileExists(atPath:alias.path) else{exit(3)}
let bookmark=try destination.bookmarkData(options:.suitableForBookmarkFile,includingResourceValuesForKeys:nil,relativeTo:nil)
try URL.writeBookmarkData(bookmark,to:alias)
var stale=false
let resolved=try URL(resolvingBookmarkData:URL.bookmarkData(withContentsOf:alias),options:[.withoutUI,.withoutMounting],relativeTo:nil,bookmarkDataIsStale:&stale)
guard !stale,resolved.resolvingSymlinksInPath()==destination.resolvingSymlinksInPath() else{exit(4)}
print("Finder alias created and destination verified")
