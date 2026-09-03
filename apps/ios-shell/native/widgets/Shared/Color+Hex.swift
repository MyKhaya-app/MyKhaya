import SwiftUI

extension Color {
    /// Parses a "#RRGGBB" or "RRGGBB" string (MyKhaya's calendar/category
    /// colour fields — see EventLabel.color / HomeCalendar.color in
    /// shared-types). Falls back to the system accent colour for anything
    /// unparsable rather than rendering invisible/black content — a widget
    /// must never show a broken swatch just because a colour string was
    /// malformed.
    init(mykhayaHex hex: String) {
        var sanitized = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        if sanitized.hasPrefix("#") { sanitized.removeFirst() }
        guard sanitized.count == 6, let value = UInt32(sanitized, radix: 16) else {
            self = .accentColor
            return
        }
        let r = Double((value >> 16) & 0xFF) / 255
        let g = Double((value >> 8) & 0xFF) / 255
        let b = Double(value & 0xFF) / 255
        self = Color(red: r, green: g, blue: b)
    }
}
