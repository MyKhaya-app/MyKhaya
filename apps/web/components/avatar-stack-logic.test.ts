import { describe, expect, it } from "vitest";
import {
  type AvatarStackPerson,
  avatarStackLabel,
  buildAvatarStack,
  MAX_STACK_AVATARS,
  participantsForEvent,
} from "./avatar-stack-logic";

function person(id: string, name: string): AvatarStackPerson {
  return { user_id: id, display_name: name, colour: null, avatar_version: null };
}

const alice = person("1", "Alice");
const bob = person("2", "Bob");
const charlie = person("3", "Charlie");
const dana = person("4", "Dana");
const evan = person("5", "Evan");

describe("buildAvatarStack", () => {
  it("shows the single person and reports no extras", () => {
    const { shown, extra } = buildAvatarStack([alice]);
    expect(shown).toEqual([alice]);
    expect(extra).toBe(0);
  });

  it("shows two people with no extras", () => {
    const { shown, extra } = buildAvatarStack([alice, bob]);
    expect(shown).toEqual([alice, bob]);
    expect(extra).toBe(0);
  });

  it("shows three people with no extras", () => {
    const { shown, extra } = buildAvatarStack([alice, bob, charlie]);
    expect(shown).toEqual([alice, bob, charlie]);
    expect(extra).toBe(0);
  });

  it("caps at MAX_STACK_AVATARS and reports the remainder for four people", () => {
    const { shown, extra } = buildAvatarStack([alice, bob, charlie, dana]);
    expect(shown).toEqual([alice, bob, charlie]);
    expect(shown.length).toBe(MAX_STACK_AVATARS);
    expect(extra).toBe(1);
  });

  it("caps at MAX_STACK_AVATARS and reports the remainder for five or more people", () => {
    const { shown, extra } = buildAvatarStack([alice, bob, charlie, dana, evan]);
    expect(shown).toEqual([alice, bob, charlie]);
    expect(extra).toBe(2);
  });

  it("never renders more than MAX_STACK_AVATARS actual avatars, however many people are passed", () => {
    const many = [alice, bob, charlie, dana, evan, person("6", "Fay"), person("7", "Gus")];
    const { shown, extra } = buildAvatarStack(many);
    expect(shown.length).toBe(MAX_STACK_AVATARS);
    expect(extra).toBe(many.length - MAX_STACK_AVATARS);
  });

  it("preserves the caller's ordering rather than reordering people", () => {
    const { shown } = buildAvatarStack([charlie, alice, bob]);
    expect(shown.map((p) => p.user_id)).toEqual(["3", "1", "2"]);
  });

  it("is empty for zero people", () => {
    const { shown, extra } = buildAvatarStack([]);
    expect(shown).toEqual([]);
    expect(extra).toBe(0);
  });
});

describe("participantsForEvent", () => {
  it("resolves event ids in roster order", () => {
    expect(participantsForEvent([charlie, alice, bob], ["2", "3"]).map((p) => p.user_id)).toEqual([
      "3",
      "2",
    ]);
  });

  it("does not infer participants from unrelated roster members", () => {
    expect(participantsForEvent([alice, bob], ["missing"]).map((p) => p.user_id)).toEqual([]);
  });
});

describe("avatarStackLabel", () => {
  it("names a single person", () => {
    expect(avatarStackLabel([alice])).toBe("Alice");
  });

  it("joins two people with 'and'", () => {
    expect(avatarStackLabel([alice, bob])).toBe("Alice and Bob");
  });

  it("lists three or more people with a conjunction before the last", () => {
    expect(avatarStackLabel([alice, bob, charlie])).toBe("Alice, Bob and Charlie");
  });

  it("still names everyone even when more than MAX_STACK_AVATARS are shown as '+N' visually", () => {
    // The label is a separate accessibility concern from what's visually
    // rendered — it should describe all associated people, not just the
    // ones with a visible circle.
    expect(avatarStackLabel([alice, bob, charlie, dana])).toBe("Alice, Bob, Charlie and Dana");
  });
});
