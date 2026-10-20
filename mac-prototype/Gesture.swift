import Foundation

struct OptionGesture {
    private(set) var down = false
    private var usedInChord = false
    mutating func rightOption(_ isDown: Bool) -> Bool {
        if isDown {
            guard !down else { return false }
            down = true; usedInChord = false
            return false
        }
        guard down else { return false }
        down = false
        return !usedInChord
    }
    mutating func otherInput() { if down { usedInChord = true } }
    mutating func reset() { down = false; usedInChord = false }
}
