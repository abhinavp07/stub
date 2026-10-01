"use client";

import { useState } from "react";

import { inputClass } from "@/components/ui";

const MAX_TAG_LENGTH = 40;
const MAX_TAGS = 50;

/** Type a tag and press Enter or comma to add it; Backspace on an empty input removes the last. */
export function TagInput({
  id,
  value,
  onChange,
  disabled,
}: {
  id: string;
  value: string[];
  onChange: (tags: string[]) => void;
  disabled?: boolean;
}) {
  const [draft, setDraft] = useState("");

  function commit(raw: string) {
    const tag = raw.trim().slice(0, MAX_TAG_LENGTH);
    setDraft("");
    if (!tag || value.includes(tag) || value.length >= MAX_TAGS) return;
    onChange([...value, tag]);
  }

  return (
    <div className="space-y-2">
      {value.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Selected tags">
          {value.map((tag) => (
            <li
              key={tag}
              className="inline-flex items-center gap-1 rounded-full bg-blue-50 py-0.5 pr-1 pl-2.5 text-xs font-medium text-blue-800"
            >
              {tag}
              <button
                type="button"
                disabled={disabled}
                onClick={() => onChange(value.filter((t) => t !== tag))}
                aria-label={`Remove tag ${tag}`}
                className="rounded-full px-1 hover:bg-blue-100 focus-visible:outline-2 focus-visible:outline-blue-600"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}
      <input
        id={id}
        value={draft}
        disabled={disabled}
        maxLength={MAX_TAG_LENGTH}
        placeholder="Add a tag and press Enter"
        className={inputClass}
        onChange={(e) => {
          const v = e.target.value;
          if (v.endsWith(",")) commit(v.slice(0, -1));
          else setDraft(v);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            e.preventDefault();
            commit(draft);
          } else if (e.key === "Backspace" && draft === "" && value.length > 0) {
            onChange(value.slice(0, -1));
          }
        }}
        onBlur={() => draft && commit(draft)}
      />
    </div>
  );
}
