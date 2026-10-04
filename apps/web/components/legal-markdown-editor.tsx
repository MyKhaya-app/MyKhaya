"use client";

import {
  BoldItalicUnderlineToggles,
  BlockTypeSelect,
  CreateLink,
  headingsPlugin,
  InsertTable,
  InsertThematicBreak,
  linkPlugin,
  listsPlugin,
  ListsToggle,
  MDXEditor,
  quotePlugin,
  Separator,
  tablePlugin,
  thematicBreakPlugin,
  toolbarPlugin,
  UndoRedo,
} from "@mdxeditor/editor";
import { useCallback, useEffect, useRef, useState } from "react";

export function LegalMarkdownEditor({
  markdown,
  onChange,
}: {
  markdown: string;
  onChange: (value: string) => void;
}) {
  const rootRef = useRef<HTMLDivElement>(null);
  const [overlayContainer, setOverlayContainer] = useState<HTMLDivElement | null>(null);
  const setRoot = useCallback((node: HTMLDivElement | null) => {
    rootRef.current = node;
    setOverlayContainer(node);
  }, []);

  useEffect(() => {
    rootRef.current?.querySelector<HTMLElement>("[contenteditable='true']")?.setAttribute(
      "aria-label",
      "Document content",
    );
  }, []);

  return (
    <div
      id="legal-draft-content"
      className="cc-legal-rich-editor"
      data-testid="legal-markdown-editor"
      ref={setRoot}
    >
      <MDXEditor
        markdown={markdown}
        onChange={onChange}
        suppressHtmlProcessing
        overlayContainer={overlayContainer}
        contentEditableClassName="cc-legal-rich-editor-content"
        plugins={[
          headingsPlugin(),
          listsPlugin(),
          quotePlugin(),
          thematicBreakPlugin(),
          linkPlugin(),
          tablePlugin(),
          toolbarPlugin({
            toolbarContents: () => (
              <>
                <span className="cc-legal-toolbar-group" aria-label="History">
                  <UndoRedo />
                </span>
                <Separator />
                <span className="cc-legal-toolbar-group" aria-label="Structure">
                  <BlockTypeSelect />
                </span>
                <Separator />
                <span className="cc-legal-toolbar-group" aria-label="Formatting">
                  <BoldItalicUnderlineToggles />
                </span>
                <Separator />
                <span className="cc-legal-toolbar-group" aria-label="Lists">
                  <ListsToggle />
                </span>
                <Separator />
                <span className="cc-legal-toolbar-group" aria-label="Insert">
                  <CreateLink />
                  <InsertTable />
                  <InsertThematicBreak />
                </span>
              </>
            ),
          }),
        ]}
      />
    </div>
  );
}
