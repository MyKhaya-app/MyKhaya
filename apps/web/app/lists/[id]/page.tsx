"use client";

import { FormEvent, use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  MoreVertical,
  Plus,
  Trash2,
} from "lucide-react";
import type { HouseholdListDetail, HouseholdListItem, ListSection, Member } from "@mykhaya/shared-types";
import { ApiError, api } from "@mykhaya/api-client";
import { AppShellContent } from "@/components/app-shell";
import { Avatar } from "@/components/avatar";
import { BottomSheet } from "@/components/bottom-sheet";
import { FormStatus } from "@/components/form-status";
import { ListScopeConfirmation } from "@/components/list-scope-confirmation";
import { useActiveHome } from "@/components/use-active-home";
import { listIconGlyph } from "../list-icons";

function loadErrorMessage(cause: unknown, fallback: string): string {
  if (cause instanceof ApiError && cause.status === 404) {
    return "That list could not be found.";
  }
  return cause instanceof ApiError ? cause.message : fallback;
}

function itemLabel(item: HouseholdListItem): string {
  return item.quantity ? `${item.quantity} × ${item.text}` : item.text;
}

export default function ListDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id: listId } = use(params);
  const { activeHomeId } = useActiveHome();
  const [list, setList] = useState<HouseholdListDetail | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [hideCompleted, setHideCompleted] = useState(false);
  const [newItemText, setNewItemText] = useState("");
  const [newItemSectionId, setNewItemSectionId] = useState("");
  const [adding, setAdding] = useState(false);
  const [editingItem, setEditingItem] = useState<HouseholdListItem | null>(null);
  const [sectionActions, setSectionActions] = useState<ListSection | null>(null);
  const [showActions, setShowActions] = useState(false);
  const [moving, setMoving] = useState(false);
  const [movingBusy, setMovingBusy] = useState(false);
  const [moveError, setMoveError] = useState("");
  const [error, setError] = useState("");
  const [notFound, setNotFound] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function load() {
    if (!activeHomeId) return;
    try {
      const result = await api.list(activeHomeId, listId);
      setList(result);
      setNewItemSectionId((current) => current || result.sections?.[0]?.id || "");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 404) setNotFound(true);
      else setError(loadErrorMessage(cause, "Could not load this list."));
    }
  }

  useEffect(() => {
    void load();
    if (activeHomeId) api.members(activeHomeId).then(setMembers).catch(() => setMembers([]));
  }, [activeHomeId, listId]);

  async function addItem(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!activeHomeId || !newItemText.trim()) return;
    setAdding(true);
    setError("");
    try {
      const payload = newItemSectionId
        ? { text: newItemText.trim(), section_id: newItemSectionId }
        : { text: newItemText.trim() };
      const result = await api.addListItem(activeHomeId, listId, payload);
      setList(result);
      setNewItemText("");
      setNewItemSectionId("");
      inputRef.current?.focus();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not add that item.");
    } finally {
      setAdding(false);
    }
  }

  async function toggleItem(item: HouseholdListItem) {
    if (!activeHomeId || !list) return;
    const nextChecked = !item.is_checked;
    // Optimistic — flip immediately, roll back if the request fails.
    setList({
      ...list,
      items: list.items.map((row) => (row.id === item.id ? { ...row, is_checked: nextChecked } : row)),
    });
    try {
      const result = await api.updateListItem(activeHomeId, listId, item.id, {
        is_checked: nextChecked,
      });
      setList(result);
    } catch (cause) {
      setList(list); // roll back to the pre-toggle snapshot
      setError(cause instanceof ApiError ? cause.message : "Could not update that item.");
    }
  }

  async function deleteItem(item: HouseholdListItem) {
    if (!activeHomeId) return;
    try {
      const result = await api.removeListItem(activeHomeId, listId, item.id);
      setList(result);
      setEditingItem(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not remove that item.");
    }
  }

  async function clearCompleted() {
    if (!activeHomeId) return;
    if (!window.confirm("Remove all completed items from this list?")) return;
    try {
      const result = await api.clearCompletedListItems(activeHomeId, listId);
      setList(result);
      setShowActions(false);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not clear completed items.");
    }
  }

  async function moveListScope() {
    if (!activeHomeId || !list) return;
    const nextScope = list.scope === "personal" ? "household" : "personal";
    setMovingBusy(true);
    setMoveError("");
    try {
      const result = await api.moveListScope(activeHomeId, listId, {
        scope: nextScope,
        expected_updated_at: list.updated_at,
      });
      setList(result);
      setMoving(false);
      setMovingBusy(false);
    } catch (cause) {
      setMoveError(cause instanceof ApiError ? cause.message : "Could not change this list's scope.");
      setMovingBusy(false);
    }
  }

  async function move(item: HouseholdListItem, direction: -1 | 1) {
    if (!activeHomeId || !list) return;
    const ids = list.items.map((row) => row.id);
    const index = ids.indexOf(item.id);
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target]!, ids[index]!];
    try {
      const result = await api.reorderListItems(activeHomeId, listId, ids);
      setList(result);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not reorder items.");
    }
  }

  async function addSection() {
    if (!activeHomeId) return;
    const name = window.prompt("Section name");
    if (!name?.trim()) return;
    try {
      setList(await api.addListSection(activeHomeId, listId, name.trim()));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not add that section.");
    }
  }

  async function reorderSections(sectionId: string, direction: -1 | 1) {
    if (!activeHomeId || !list) return;
    const ids = (list.sections ?? []).map((section) => section.id);
    const index = ids.indexOf(sectionId);
    const target = index + direction;
    if (target < 0 || target >= ids.length) return;
    [ids[index], ids[target]] = [ids[target]!, ids[index]!];
    try {
      setList(await api.reorderListSections(activeHomeId, listId, ids));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not reorder sections.");
    }
  }

  async function renameSection(sectionId: string, currentName: string) {
    if (!activeHomeId || !list) return;
    const name = window.prompt("Section name", currentName);
    if (!name?.trim() || name.trim() === currentName) return;
    try {
      const section = list.sections?.find((row) => row.id === sectionId);
      if (!section || !section.updated_at) return;
      setList(
        await api.renameListSection(activeHomeId, listId, sectionId, {
          name: name.trim(),
          expected_updated_at: section.updated_at,
        }),
      );
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not rename that section.");
    }
  }

  async function removeSection(sectionId: string, name: string) {
    if (!activeHomeId || !window.confirm(`Remove “${name}”? Its items will move to Uncategorised.`)) return;
    try {
      setList(await api.removeListSection(activeHomeId, listId, sectionId));
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not remove that section.");
    }
  }

  if (notFound) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <Link className="tertiary" href="/lists">
            <ChevronLeft size={16} aria-hidden="true" /> Lists
          </Link>
          <p className="empty-mini">That list could not be found.</p>
        </main>
      </AppShellContent>
    );
  }

  if (!activeHomeId || !list) {
    return (
      <AppShellContent>
        <main className="standard-page">
          <p role="status">Loading list…</p>
        </main>
      </AppShellContent>
    );
  }

  const Glyph = listIconGlyph(list.icon);
  const sections = list.sections ?? [];
  const visibleItems = hideCompleted ? list.items.filter((item) => !item.is_checked) : list.items;
  const allComplete = list.item_count > 0 && list.remaining_count === 0;
  const renderItem = (item: HouseholdListItem) => {
    const assigned = members.find((member) => member.user_id === item.assigned_member_id);
    return (
      <div className={`lists-item-row${item.is_checked ? " checked" : ""}`} key={item.id}>
        <label className="lists-item-check">
          <input type="checkbox" checked={item.is_checked} onChange={() => void toggleItem(item)} aria-label={`Mark ${item.text} ${item.is_checked ? "not complete" : "complete"}`} />
        </label>
        <button type="button" className="lists-item-text" onClick={() => setEditingItem(item)}>
          <span>{itemLabel(item)}</span>
          {item.note && <span className="quiet-state">{item.note}</span>}
        </button>
        {assigned && <Avatar id={assigned.user_id} name={assigned.display_name} colour={assigned.colour} avatarVersion={assigned.avatar_version} size="sm" />}
      </div>
    );
  };

  return (
    <AppShellContent>
      <main className="standard-page lists-detail-page">
        <Link className="tertiary lists-back-link" href="/lists">
          <ChevronLeft size={16} aria-hidden="true" /> Lists
        </Link>
        <div className="page-heading lists-detail-heading">
          <div>
            <p className="eyebrow">
              <Glyph size={14} aria-hidden="true" /> List
            </p>
            <h1>{list.name}</h1>
          </div>
          <button
            type="button"
            className="icon-button secondary"
            aria-label="List actions"
            onClick={() => setShowActions(true)}
          >
            <MoreVertical size={18} aria-hidden="true" />
          </button>
        </div>
        <FormStatus error={error} />

        <p className="lists-progress">
          {list.item_count === 0
            ? "Nothing here yet"
            : allComplete
              ? "All done ✓"
              : `${list.remaining_count} of ${list.item_count} remaining`}
        </p>

        <form className="lists-add-item" onSubmit={addItem}>
          <input
            ref={inputRef}
            value={newItemText}
            onChange={(event) => setNewItemText(event.target.value)}
            placeholder="Add an item…"
            maxLength={200}
            aria-label="Add an item"
          />
          <button type="submit" className="icon-button" disabled={adding || !newItemText.trim()} aria-label="Add item">
            <Plus size={18} aria-hidden="true" />
          </button>
        </form>
        {sections.length > 0 && (
          <div className="lists-item-section-picker">
            <label><span>Add to:</span><select value={newItemSectionId} onChange={(event) => setNewItemSectionId(event.target.value)} aria-label="Item section">
              <option value="">Uncategorised</option>
              {sections.map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}
            </select></label>
          </div>
        )}

        {list.item_count > 0 && (
          <button
            type="button"
            className="tertiary lists-toggle-completed"
            onClick={() => setHideCompleted((current) => !current)}
          >
            {hideCompleted ? "Show completed" : "Hide completed"}
          </button>
        )}

        {sections.length > 0 ? (
          <div className="lists-section-list">
            {sections.map((section) => (
              <section className="lists-section" key={section.id}>
                <div className="lists-section-heading">
                  <h2>{section.name} <span className="lists-section-count">({list.items.filter((item) => item.section_id === section.id).length})</span></h2>
                  <button type="button" className="icon-button secondary" aria-label={`${section.name} section actions`} onClick={() => setSectionActions(section)}>
                    <MoreVertical size={18} aria-hidden="true" />
                  </button>
                </div>
                <div className="lists-item-list">{list.items.filter((item) => item.section_id === section.id && (!hideCompleted || !item.is_checked)).map(renderItem)}</div>
                {list.items.filter((item) => item.section_id === section.id).length === 0 && (
                  <div className="lists-section-empty"><strong>No items yet</strong><span>Add items to this section</span></div>
                )}
              </section>
            ))}
            {list.items.some((item) => item.section_id === null && (!hideCompleted || !item.is_checked)) && (
              <section className="lists-section"><div className="lists-section-heading"><h2>Uncategorised <span className="lists-section-count">({list.items.filter((item) => item.section_id === null).length})</span></h2></div><div className="lists-item-list">{list.items.filter((item) => item.section_id === null && (!hideCompleted || !item.is_checked)).map(renderItem)}</div></section>
            )}
          </div>
        ) : list.item_count === 0 ? (
          <p className="empty-mini">Add the first item to this list.</p>
        ) : (
          <div className="lists-item-list">
            {visibleItems.map(renderItem)}
          </div>
        )}

        {sections.length > 0 && (
          <button type="button" className="lists-add-section" onClick={() => void addSection()}>
            <Plus size={20} aria-hidden="true" /> Add section
          </button>
        )}

        {sectionActions && (
          <BottomSheet title={`${sectionActions.name} actions`} onDismiss={() => setSectionActions(null)}>
            <div className="lists-section-actions-sheet">
              <button type="button" className="secondary" onClick={() => { setSectionActions(null); void renameSection(sectionActions.id, sectionActions.name); }}>
                Rename section
              </button>
              <button type="button" className="secondary" disabled={sections.findIndex((section) => section.id === sectionActions.id) === 0} onClick={() => { setSectionActions(null); void reorderSections(sectionActions.id, -1); }}>
                <ArrowUp size={14} aria-hidden="true" /> Move up
              </button>
              <button type="button" className="secondary" disabled={sections.findIndex((section) => section.id === sectionActions.id) === sections.length - 1} onClick={() => { setSectionActions(null); void reorderSections(sectionActions.id, 1); }}>
                <ArrowDown size={14} aria-hidden="true" /> Move down
              </button>
              <button type="button" className="secondary" onClick={() => { setSectionActions(null); void removeSection(sectionActions.id, sectionActions.name); }}>
                <Trash2 size={16} aria-hidden="true" /> Remove section
              </button>
            </div>
          </BottomSheet>
        )}

        {showActions && (
          <BottomSheet title="List actions" onDismiss={() => setShowActions(false)}>
            <div className="meal-actions-sheet">
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setShowActions(false);
                  setMoveError("");
                  setMoving(true);
                }}
              >
                Move to {list.scope === "personal" ? "Household" : "Personal"}
              </button>
              <button
                type="button"
                className="secondary"
                onClick={() => void clearCompleted()}
                disabled={!list.items.some((item) => item.is_checked)}
              >
                <Trash2 size={16} aria-hidden="true" /> Clear completed
              </button>
            </div>
          </BottomSheet>
        )}

        {moving && (
          <ListScopeConfirmation
            currentScope={list.scope}
            busy={movingBusy}
            error={moveError}
            onCancel={() => {
              if (!movingBusy) setMoving(false);
            }}
            onConfirm={() => void moveListScope()}
          />
        )}

        {editingItem && (
          <EditItemSheet
            homeId={activeHomeId}
            listId={listId}
            item={editingItem}
            sections={sections}
            members={members}
            canMoveUp={list.items.findIndex((row) => row.id === editingItem.id) > 0}
            canMoveDown={
              list.items.findIndex((row) => row.id === editingItem.id) < list.items.length - 1
            }
            onMove={(direction) => void move(editingItem, direction)}
            onClose={() => setEditingItem(null)}
            onDelete={() => void deleteItem(editingItem)}
            onSaved={(updated) => {
              setList(updated);
              setEditingItem(null);
            }}
          />
        )}
      </main>
    </AppShellContent>
  );
}

function EditItemSheet({
  homeId,
  listId,
  item,
  sections,
  members,
  canMoveUp,
  canMoveDown,
  onMove,
  onClose,
  onDelete,
  onSaved,
}: {
  homeId: string;
  listId: string;
  item: HouseholdListItem;
  sections: HouseholdListDetail["sections"];
  members: Member[];
  canMoveUp: boolean;
  canMoveDown: boolean;
  onMove: (direction: -1 | 1) => void;
  onClose: () => void;
  onDelete: () => void;
  onSaved: (list: HouseholdListDetail) => void;
}) {
  const [text, setText] = useState(item.text);
  const [quantity, setQuantity] = useState(item.quantity ?? "");
  const [note, setNote] = useState(item.note ?? "");
  const [assignedTo, setAssignedTo] = useState(item.assigned_member_id ?? "");
  const [sectionId, setSectionId] = useState(item.section_id ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!text.trim()) {
      setError("Give this item some text.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await api.updateListItem(homeId, listId, item.id, {
        text: text.trim(),
        quantity: quantity.trim() || null,
        note: note.trim() || null,
        assigned_member_id: assignedTo || null,
        section_id: sectionId || null,
      });
      onSaved(result);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "Could not save this item.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <BottomSheet title="Edit item" onDismiss={onClose}>
      <form onSubmit={submit}>
        <label>
          Item
          <input value={text} onChange={(event) => setText(event.target.value)} maxLength={200} required />
        </label>
        <div className="meal-time-row">
          <label>
            Quantity (optional)
            <input
              value={quantity}
              onChange={(event) => setQuantity(event.target.value)}
              placeholder="e.g. 2"
              maxLength={40}
            />
          </label>
          <label>
            Assign to (optional)
            <select value={assignedTo} onChange={(event) => setAssignedTo(event.target.value)}>
              <option value="">No one</option>
              {members.map((member) => (
                <option key={member.user_id} value={member.user_id}>
                  {member.display_name}
                </option>
              ))}
            </select>
          </label>
        </div>
        <label>
          Note (optional)
          <input value={note} onChange={(event) => setNote(event.target.value)} maxLength={500} />
        </label>
        {sections.length > 0 && (
          <label>
            Section
            <select value={sectionId} onChange={(event) => setSectionId(event.target.value)}>
              <option value="">Uncategorised</option>
              {sections.map((section) => <option key={section.id} value={section.id}>{section.name}</option>)}
            </select>
          </label>
        )}
        <FormStatus error={error} />
        <button className="sheet-primary" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </button>
        <div className="lists-edit-item-secondary">
          <button
            type="button"
            className="secondary"
            disabled={!canMoveUp}
            onClick={() => onMove(-1)}
          >
            <ArrowUp size={14} aria-hidden="true" /> Move up
          </button>
          <button
            type="button"
            className="secondary"
            disabled={!canMoveDown}
            onClick={() => onMove(1)}
          >
            <ArrowDown size={14} aria-hidden="true" /> Move down
          </button>
        </div>
        <button type="button" className="secondary" onClick={onDelete}>
          <Trash2 size={16} aria-hidden="true" /> Remove item
        </button>
      </form>
    </BottomSheet>
  );
}
