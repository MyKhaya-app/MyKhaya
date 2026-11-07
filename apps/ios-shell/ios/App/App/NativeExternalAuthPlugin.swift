import AuthenticationServices
import Capacitor
import CryptoKit

/// Native provider boundary for the shared web UI. The API supplies a nonce;
/// Apple's SDK receives only its SHA-256 form, while the signed identity token
/// is returned to the web layer for server-side verification. No Apple token
/// is persisted or logged by the shell.
///
/// Requires the `com.apple.developer.applesignin` entitlement in the signed
/// app (AppDebug/AppRelease.entitlements). Without it every request fails with
/// ASAuthorizationError.unknown (1000) before any Apple UI appears.
///
/// Failures reject with a stable, non-sensitive `code` so the web layer can
/// tell cancellation, configuration and provider failures apart:
/// `cancelled`, `apple_unknown` (1000: missing entitlement, or no Apple Account
/// on the device), `apple_failed`, `apple_invalid_response`,
/// `apple_not_handled`, `apple_not_interactive`, `apple_other`,
/// `invalid_credential`, `invalid_transaction`, `in_progress`. `data.native_code`
/// carries the numeric ASAuthorizationError code only — never tokens or user data.
@objc(NativeExternalAuthPlugin)
public class NativeExternalAuthPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NativeExternalAuthPlugin"
    public let jsName = "NativeExternalAuth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "signInApple", returnType: CAPPluginReturnPromise),
    ]

    /// Only touched on the main queue.
    private var pendingCall: CAPPluginCall?
    private var controller: ASAuthorizationController?

    @objc func signInApple(_ call: CAPPluginCall) {
        guard let nonce = call.getString("nonce"), nonce.count >= 20, nonce.count <= 200 else {
            call.reject("Invalid sign-in transaction", "invalid_transaction")
            return
        }
        // Capacitor invokes plugin methods off the main thread; AuthenticationServices
        // presentation and the anchor lookup below are UIKit work.
        DispatchQueue.main.async { [weak self] in
            guard let self else {
                call.reject("Apple sign-in could not be completed", "apple_other")
                return
            }
            guard self.pendingCall == nil else {
                call.reject("A provider sign-in is already in progress", "in_progress")
                return
            }
            self.pendingCall = call
            let request = ASAuthorizationAppleIDProvider().createRequest()
            request.requestedScopes = [.email, .fullName]
            request.nonce = SHA256.hash(data: Data(nonce.utf8)).map { String(format: "%02x", $0) }.joined()
            let controller = ASAuthorizationController(authorizationRequests: [request])
            controller.delegate = self
            controller.presentationContextProvider = self
            self.controller = controller
            controller.performRequests()
        }
    }

    private func resolve(_ payload: [String: Any]) {
        guard let call = pendingCall else { return }
        pendingCall = nil
        controller = nil
        call.resolve(payload)
    }

    private func reject(code: String, nativeCode: Int?) {
        guard let call = pendingCall else { return }
        pendingCall = nil
        controller = nil
        let message = code == "cancelled" ? "Apple sign-in was cancelled" : "Apple sign-in could not be completed"
        var data: [String: Any] = [:]
        if let nativeCode { data["native_code"] = nativeCode }
        call.reject(message, code, nil, data)
    }

    private static func failureCode(for error: Error) -> (String, Int?) {
        guard let authError = error as? ASAuthorizationError else { return ("apple_other", nil) }
        let raw = authError.code.rawValue
        switch authError.code {
        case .canceled: return ("cancelled", raw)
        case .unknown: return ("apple_unknown", raw)
        case .failed: return ("apple_failed", raw)
        case .invalidResponse: return ("apple_invalid_response", raw)
        case .notHandled: return ("apple_not_handled", raw)
        case .notInteractive: return ("apple_not_interactive", raw)
        default: return ("apple_other", raw)
        }
    }
}

extension NativeExternalAuthPlugin: ASAuthorizationControllerDelegate {
    public func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
                  let tokenData = credential.identityToken,
                  let token = String(data: tokenData, encoding: .utf8) else {
                self.reject(code: "invalid_credential", nativeCode: nil)
                return
            }
            var payload: [String: Any] = ["identity_token": token]
            if let email = credential.email { payload["email"] = email }
            if let name = credential.fullName?.formatted(), !name.isEmpty { payload["display_name"] = name }
            self.resolve(payload)
        }
    }

    public func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        let (code, nativeCode) = Self.failureCode(for: error)
        DispatchQueue.main.async { [weak self] in
            self?.reject(code: code, nativeCode: nativeCode)
        }
    }
}

extension NativeExternalAuthPlugin: ASAuthorizationControllerPresentationContextProviding {
    public func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        return bridge?.viewController?.view.window ?? ASPresentationAnchor()
    }
}
