"use client";

import { Lock, MessageCircle } from "lucide-react";

// Framework-only placeholder for the Family tab's chat card — see the
// "Family chat" section of the Family redesign task. Deliberately no
// message storage, no realtime transport, no crypto: this establishes the
// visual slot and a clean prop shape so a real, properly security-reviewed
// E2EE implementation can be dropped in later without reworking the Family
// page around it.
//
// `enabled` gates the whole feature (a narrowly-scoped UI-only flag, not a
// backend FeatureKey — there is no chat backend yet for a flag to gate) and
// defaults to false; `messages`/`unreadCount` are for a future real data
// source and are only ever rendered when the caller actually has some to
// show (never fabricated here or by any caller).
export interface FamilyChatMessage {
  id: string;
  authorId: string;
  authorName: string;
  authorColour?: string | null;
  authorAvatarVersion?: string | null;
  preview: string;
  timeLabel: string;
}

export interface FamilyChatPreviewProps {
  enabled: boolean;
  unreadCount?: number;
  messages?: FamilyChatMessage[];
  onOpen?: () => void;
}

export function FamilyChatPreview({
  enabled,
  unreadCount,
  messages = [],
  onOpen,
}: FamilyChatPreviewProps) {
  return (
    <section className="card family-chat-card">
      <div className="section-heading">
        <div>
          <h2>Family chat</h2>
          <p className="family-chat-lock">
            <Lock size={13} aria-hidden="true" />
            Private to your family
          </p>
        </div>
        {enabled && typeof unreadCount === "number" && unreadCount > 0 && (
          <span className="family-chat-unread">{unreadCount} new</span>
        )}
      </div>

      {enabled ? (
        <>
          <div className="family-chat-messages">
            {messages.slice(0, 2).map((message) => (
              <div className="family-chat-message" key={message.id}>
                <strong>{message.authorName}</strong>
                <span className="family-chat-time">{message.timeLabel}</span>
                <p>{message.preview}</p>
              </div>
            ))}
          </div>
          <button type="button" className="tertiary family-chat-open" onClick={onOpen}>
            Open chat
          </button>
        </>
      ) : (
        <div className="family-chat-placeholder" role="status">
          <MessageCircle size={20} aria-hidden="true" />
          <p>Family chat is coming soon.</p>
          <button type="button" className="secondary" disabled aria-disabled="true">
            Open chat
          </button>
        </div>
      )}
    </section>
  );
}
