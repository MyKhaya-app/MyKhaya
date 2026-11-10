package app.mykhaya.mobile;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import androidx.credentials.Credential;
import androidx.credentials.CredentialManager;
import androidx.credentials.CredentialManagerCallback;
import androidx.credentials.CustomCredential;
import androidx.credentials.GetCredentialRequest;
import androidx.credentials.GetCredentialResponse;
import androidx.credentials.exceptions.GetCredentialException;
import com.google.android.libraries.identity.googleid.GetGoogleIdOption;
import com.google.android.libraries.identity.googleid.GoogleIdTokenCredential;

import java.util.concurrent.Executors;

/** Google Identity Services boundary. The ID token is returned once to the
 * web layer for immediate server verification and is never persisted/logged
 * by the shell. Apple remains a system-browser flow on Android. */
@CapacitorPlugin(name = "NativeExternalAuth")
public class NativeExternalAuthPlugin extends Plugin {
    @PluginMethod
    public void signInGoogle(PluginCall call) {
        String clientId = call.getString("client_id");
        String nonce = call.getString("nonce");
        if (clientId == null || clientId.isEmpty() || nonce == null || nonce.length() < 20) {
            call.reject("Invalid sign-in transaction");
            return;
        }
        GetGoogleIdOption option = new GetGoogleIdOption.Builder()
            .setServerClientId(clientId)
            .setFilterByAuthorizedAccounts(false)
            .setNonce(nonce)
            .build();
        GetCredentialRequest request = new GetCredentialRequest.Builder()
            .addCredentialOption(option)
            .build();
        CredentialManager manager = CredentialManager.create(getContext());
        manager.getCredentialAsync(
            getContext(),
            request,
            null,
            Executors.newSingleThreadExecutor(),
            new CredentialManagerCallback<GetCredentialResponse, GetCredentialException>() {
                @Override
                public void onResult(GetCredentialResponse result) {
                    try {
                        Credential credential = result.getCredential();
                        if (!(credential instanceof CustomCredential)
                            || !GoogleIdTokenCredential.TYPE_GOOGLE_ID_TOKEN_CREDENTIAL.equals(((CustomCredential) credential).getType())) {
                            call.reject("Google sign-in could not be completed");
                            return;
                        }
                        GoogleIdTokenCredential google = GoogleIdTokenCredential.createFrom(((CustomCredential) credential).getData());
                        JSObject response = new JSObject();
                        response.put("identity_token", google.getIdToken());
                        call.resolve(response);
                    } catch (Exception ignored) {
                        call.reject("Google sign-in could not be completed");
                    }
                }

                @Override
                public void onError(GetCredentialException error) {
                    call.reject("Google sign-in was cancelled");
                }
            }
        );
    }
}
