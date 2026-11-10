# Firebase service-account rotation

This runbook covers the Android FCM service-account key used by the API worker.
It does not apply to the Android `google-services.json`, which is a client
configuration file and must never contain a service-account private key.

The expected Firebase projects are:

| Environment | FCM project |
| --- | --- |
| DEV | `mykhaya-dev-faf55` |
| PROD | `mykhaya-prod` |

## Rotation sequence

1. Create a replacement key for the existing environment-specific Firebase
   service account in the appropriate Google Cloud/Firebase project. Download
   it to a location outside the repository, outside Docker build contexts, and
   outside backup/screenshot folders.
2. Restrict the replacement file to the deployment operator account. Do not
   paste the JSON or PEM into tickets, chat, shell history, CI logs, Compose
   output, or source control.
3. Extract only the required values into the environment-specific secret
   store: `project_id`, `client_email`, and `private_key`. The worker accepts
   the PEM with literal newlines or escaped `\n` characters.
4. Set `MYKHAYA_FCM_DELIVERY_CONFIGURED=true` only after all three values are
   present. DEV must use `mykhaya-dev-faf55`; PROD must use `mykhaya-prod`.
5. Deploy the changed secret through the normal environment deployment
   process. Do not use `docker compose config` without masking because Compose
   interpolation can reveal private values.
6. Before sending a notification, inspect only masked metadata from the worker:
   environment, project ID, presence of client email, presence of PEM, and PEM
   begin/end markers. Run PEM parsing and the Google OAuth token exchange while
   printing only success/failure; never print the access token.
7. After the replacement key is verified, revoke the old key in the same
   environment's service account. Because the DEV key was exposed in tool
   output, its revocation should not wait for a successful notification test.
8. Review Google Cloud audit logs and MyKhaya worker logs for use of the old
   key. Do not include bearer tokens, private keys, or device registration
   tokens in the review record.

## Deployment invariants

Production startup now fails if FCM delivery is enabled without a complete
PKCS#8 PEM configuration or if the project is anything other than
`mykhaya-prod`. FCM failures are classified as authentication, invalid-request,
permanent-token, or transient-provider failures; only transient failures are
retried.

The safe verification order is configuration metadata, PEM parsing, OAuth token
acquisition, device-registration/provider correlation, then one explicitly
approved notification. A successful OAuth exchange proves service-account
authorization only; it does not prove that an Android device has permission or
that a token is still registered.
