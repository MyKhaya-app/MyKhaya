import AuthenticationServices
import Capacitor
import CryptoKit

/// Native provider boundary for the shared web UI. The API supplies a nonce;
/// Apple's SDK receives only its SHA-256 form, while the signed identity token
/// is returned to the web layer for server-side verification. No Apple token
/// is persisted or logged by the shell.
///
/// Requires the `com.apple.developer.applesignin` entitlement in the signed
/// app. Without it AuthenticationServices fails with ASAuthorizationError.unknown.
/// Failures reject with stable, non-sensitive codes and only the numeric native
/// error code; identity tokens and user data are never logged.
@objc(NativeExternalAuthPlugin)
public class NativeExternalAuthPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NativeExternalAuthPlugin"
    public let jsName = "NativeExternalAuth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "signInApple", returnType: CAPPluginReturnPromise),
    ]

    private var pendingCall: CAPPluginCall?
    private var controller: ASAuthorizationController?

    @objc func signInApple(_ call: CAPPluginCall) {
        guard let nonce = call.getString("nonce"), nonce.count >= 20, nonce.count <= 200 else {
            call.reject("Invalid sign-in transaction", "invalid_transaction")
            return
        }
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
