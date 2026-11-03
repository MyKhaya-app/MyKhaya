import AuthenticationServices
import Capacitor
import CryptoKit

/// Native provider boundary for the shared web UI. The API supplies a nonce;
/// Apple's SDK receives only its SHA-256 form, while the signed identity token
/// is returned to the web layer for server-side verification. No Apple token
/// is persisted or logged by the shell.
@objc(NativeExternalAuthPlugin)
public class NativeExternalAuthPlugin: CAPPlugin, CAPBridgedPlugin {
    public let identifier = "NativeExternalAuthPlugin"
    public let jsName = "NativeExternalAuth"
    public let pluginMethods: [CAPPluginMethod] = [
        CAPPluginMethod(name: "signInApple", returnType: CAPPluginReturnPromise),
    ]

    private var pendingCall: CAPPluginCall?

    @objc func signInApple(_ call: CAPPluginCall) {
        guard let nonce = call.getString("nonce"), nonce.count >= 20, nonce.count <= 200 else {
            call.reject("Invalid sign-in transaction")
            return
        }
        guard pendingCall == nil else {
            call.reject("A provider sign-in is already in progress")
            return
        }
        pendingCall = call
        let request = ASAuthorizationAppleIDProvider().createRequest()
        request.requestedScopes = [.email, .fullName]
        request.nonce = SHA256.hash(data: Data(nonce.utf8)).map { String(format: "%02x", $0) }.joined()
        let controller = ASAuthorizationController(authorizationRequests: [request])
        controller.delegate = self
        controller.presentationContextProvider = self
        controller.performRequests()
    }


    private func finish(_ result: Result<[String: Any], Error>) {
        guard let call = pendingCall else { return }
        pendingCall = nil
        switch result {
        case .success(let payload): call.resolve(payload)
        case .failure: call.reject("Apple sign-in could not be completed")
        }
    }
}

extension NativeExternalAuthPlugin: ASAuthorizationControllerDelegate {
    public func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithAuthorization authorization: ASAuthorization
    ) {
        guard let credential = authorization.credential as? ASAuthorizationAppleIDCredential,
              let tokenData = credential.identityToken,
              let token = String(data: tokenData, encoding: .utf8) else {
            finish(.failure(NSError(domain: "MyKhayaAuth", code: 1)))
            return
        }
        var payload: [String: Any] = ["identity_token": token]
        if let email = credential.email { payload["email"] = email }
        if let name = credential.fullName?.formatted() { payload["display_name"] = name }
        finish(.success(payload))
    }

    public func authorizationController(
        controller: ASAuthorizationController,
        didCompleteWithError error: Error
    ) {
        finish(.failure(error))
    }
}

extension NativeExternalAuthPlugin: ASAuthorizationControllerPresentationContextProviding {
    public func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        return bridge?.viewController?.view.window ?? ASPresentationAnchor()
    }
}
