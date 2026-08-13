/** Pure participant-selection logic for AvatarStack (avatar.tsx), kept
 * separate so it's unit-testable without mounting the component — same
 * convention as platform-mfa-logic.ts. */

export type AvatarStackPerson = {
  user_id: string;
  display_name: string;
  colour?: string | null;
  avatar_version?: string | null;
};

export const MAX_STACK_AVATARS = 3;

/** Which avatars to actually render, and how many are left over for the
 * "+N" tile. `people` order is the caller's to decide (see home/page.tsx,
 * which reuses GET /groups/{id}/members' existing display_name order) —
 * this never reorders it. */
export function buildAvatarStack(
  people: AvatarStackPerson[],
  max: number = MAX_STACK_AVATARS,
): { shown: AvatarStackPerson[]; extra: number } {
  const shown = people.slice(0, max);
  return { shown, extra: people.length - shown.length };
}

/** One combined "Alice, Bob and Charlie" label for the whole group, so a
 * screen reader announces the group once rather than once per circle. */
export function avatarStackLabel(people: AvatarStackPerson[]): string {
  return new Intl.ListFormat("en-GB", { style: "long", type: "conjunction" }).format(
    people.map((person) => person.display_name),
  );
}
