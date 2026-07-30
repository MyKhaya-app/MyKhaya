// Generated from apps/api/openapi.json by `make generate-client` in CI.
// This small bootstrap surface is replaced by generation once the API starts.
export type MembershipRole = "owner" | "administrator" | "adult_member" | "member" | "guest";
export interface User { id: string; email: string; display_name: string; email_verified: boolean }
export interface Home { id: string; name: string; role: MembershipRole; member_count: number }
export interface Member { user_id: string; display_name: string; email: string; role: MembershipRole }

