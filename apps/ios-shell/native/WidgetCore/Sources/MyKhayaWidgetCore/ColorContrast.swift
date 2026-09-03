import Foundation

// Pure RGB/luminance math for choosing readable event-tile text colour.
// No SwiftUI dependency (so it's linkable by XCTest and usable from the App
// target too, not just the widget extension) — mirrors the hex parsing in
// apps/ios-shell/native/widgets/Shared/Color+Hex.swift's SwiftUI
// extension, kept in sync by hand since that file must stay UI-only to
// live outside this package.

public struct HexRGB: Equatable, Sendable {
    public let red: Double
    public let green: Double
    public let blue: Double
}

/// Parses a "#RRGGBB" or "RRGGBB" string. Returns nil for anything else
/// rather than guessing — callers decide their own safe fallback.
public func parseHexRGB(_ hex: String) -> HexRGB? {
    var sanitized = hex.trimmingCharacters(in: .whitespacesAndNewlines)
    if sanitized.hasPrefix("#") { sanitized.removeFirst() }
    guard sanitized.count == 6, let value = UInt32(sanitized, radix: 16) else { return nil }
    let r = Double((value >> 16) & 0xFF) / 255
    let g = Double((value >> 8) & 0xFF) / 255
    let b = Double(value & 0xFF) / 255
    return HexRGB(red: r, green: g, blue: b)
}

/// True if `hex` is light enough that dark text reads clearly on top of it
/// (callers should use light/white text when this is false). Uses the
/// standard perceptive-luminance weighting (ITU-R BT.601: 0.299R + 0.587G +
/// 0.114B), threshold 0.6 — slightly above the textbook 0.5 midpoint
/// because MyKhaya's calendar colour palette leans toward saturated
/// mid-tones (e.g. mid-saturation yellow/orange) that read more reliably
/// with dark text than a strict 0.5 split would choose. Falls back to
/// `true` (dark text) for an unparsable hex — matches
/// Color(mykhayaHex:)'s own fallback-to-accentColor philosophy of never
/// silently rendering something illegible.
public func isLightBackground(hex: String) -> Bool {
    guard let rgb = parseHexRGB(hex) else { return true }
    let luminance = 0.299 * rgb.red + 0.587 * rgb.green + 0.114 * rgb.blue
    return luminance > 0.6
}
