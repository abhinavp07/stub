import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { TagInput } from "@/components/TagInput";

function Harness({ initial = [] as string[] }) {
  const [tags, setTags] = useState(initial);
  return (
    <>
      <label htmlFor="t">Tags</label>
      <TagInput id="t" value={tags} onChange={setTags} />
      <output data-testid="value">{JSON.stringify(tags)}</output>
    </>
  );
}

const value = () => JSON.parse(screen.getByTestId("value").textContent ?? "[]");

describe("TagInput", () => {
  it("adds tags on Enter and comma, trimming and skipping duplicates", async () => {
    render(<Harness />);
    const user = userEvent.setup();
    const input = screen.getByLabelText("Tags");
    await user.type(input, " work {Enter}");
    await user.type(input, "travel,");
    await user.type(input, "work{Enter}");
    expect(value()).toEqual(["work", "travel"]);
    expect(input).toHaveValue("");
  });

  it("removes tags with the button or Backspace", async () => {
    render(<Harness initial={["a", "b", "c"]} />);
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Remove tag b" }));
    expect(value()).toEqual(["a", "c"]);
    await user.type(screen.getByLabelText("Tags"), "{Backspace}");
    expect(value()).toEqual(["a"]);
  });
});
