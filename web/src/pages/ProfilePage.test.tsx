import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { App } from "../App";
import type { ProfileDraft, ProfileResponse } from "../api/types";
import { saveProfileDraft } from "../lib/profileStorage";
import { jsonOk, makeFields, makeSummary } from "../test/factories";

const options = {
  schema_version: 1,
  importance: [
    { value: "core", label: "Core" },
    { value: "interested", label: "Interested" },
    { value: "occasional", label: "Occasional" },
  ],
  avoidance: [
    { value: "avoid", label: "Avoid" },
    { value: "less", label: "Less" },
  ],
  freshness: [
    { value: "newest_first", label: "Mostly newest" },
    { value: "balanced", label: "Balanced" },
    { value: "relevance_first", label: "Best match" },
  ],
  exploration: [
    { value: "focused", label: "Focused" },
    { value: "balanced", label: "Balanced" },
    { value: "adventurous", label: "Adjacent" },
  ],
  publication: [
    { value: "include_preprints", label: "Include preprints" },
    { value: "prefer_peer_reviewed", label: "Prefer peer reviewed" },
    { value: "peer_reviewed_only", label: "Peer reviewed only" },
  ],
  limits: { interest_characters: 200, example_papers: 8 },
};

const emptyDraft: ProfileDraft = {
  fields: [],
  interests: [],
  example_papers: [],
  negatives: [],
  negative_papers: [],
  blocked_topics: [],
  discovery: {
    freshness: "balanced",
    exploration: "balanced",
    publication: "include_preprints",
  },
};

function response(draft: ProfileDraft): ProfileResponse {
  return {
    schema_version: 1,
    draft,
    profile: {
      schema_version: 1,
      model_key: "specter2",
      interests: [],
      preferences: [],
      blocked_topics: [],
      peer_reviewed_only: false,
    },
    summary: {
      sections: [{ heading: "Broad areas", items: ["Computer Science"] }],
      preferences: [{ label: "Discovery", value: "Balanced" }],
    },
    preview: [
      {
        rank: 1,
        paper: makeSummary({ id: "paper-1", title: "A useful recommendation paper" }),
        matched_interest: "Computer Science",
        matched_interest_key: "field:computer-science",
        reasons: ["Matches Computer Science"],
        is_exploration: false,
        is_retracted: false,
      },
    ],
    issues: [],
    changes: [],
  };
}

function renderProfile() {
  return render(
    <MemoryRouter initialEntries={["/profile"]}>
      <App />
    </MemoryRouter>,
  );
}

describe("research profile", () => {
  it("lets a reader forget a profile retained on this device", async () => {
    const user = userEvent.setup();
    saveProfileDraft({ ...emptyDraft, fields: ["computer-science"] });
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const path = new URL(input, "http://api.test").pathname;
        if (path === "/fields") {
          return Promise.resolve(jsonOk(makeFields({ "computer-science": 1 })));
        }
        if (path === "/profiles/options") return Promise.resolve(jsonOk(options));
        return Promise.reject(new Error(`unhandled path ${path}`));
      }),
    );

    renderProfile();

    const forget = await screen.findByRole("button", { name: "Forget this profile" });
    const computerScience = await screen.findByRole("button", { name: "Computer Science" });
    expect(computerScience).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(forget);

    expect(window.localStorage.getItem("academious:profile:v1")).toBeNull();
    expect(screen.queryByRole("button", { name: "Forget this profile" })).not.toBeInTheDocument();
    expect(computerScience).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("is reachable from the application header", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((input: string) => {
        const path = new URL(input, "http://api.test").pathname;
        if (path === "/fields") return Promise.resolve(jsonOk(makeFields()));
        if (path === "/profiles/options") return Promise.resolve(jsonOk(options));
        return Promise.reject(new Error(`unhandled path ${path}`));
      }),
    );

    renderProfile();

    expect(
      await screen.findByRole("heading", { level: 1, name: "Your research profile" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Interests" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("posts the reader's draft and renders the feed it produces", async () => {
    const user = userEvent.setup();
    const mock = vi.fn((input: string, init?: RequestInit) => {
      const path = new URL(input, "http://api.test").pathname;
      if (path === "/fields") return Promise.resolve(jsonOk(makeFields()));
      if (path === "/profiles/options") return Promise.resolve(jsonOk(options));
      if (path === "/profiles/preview") {
        const body = JSON.parse(String(init?.body)) as { draft: ProfileDraft };
        return Promise.resolve(jsonOk(response(body.draft)));
      }
      return Promise.reject(new Error(`unhandled path ${path}`));
    });
    vi.stubGlobal("fetch", mock);
    renderProfile();

    const field = await screen.findByRole("button", { name: "Computer Science" });
    await user.click(field);
    await user.click(screen.getByRole("button", { name: "Show me my feed" }));

    expect(
      await screen.findByRole("link", { name: "A useful recommendation paper" }),
    ).toBeInTheDocument();
    const previewCall = mock.mock.calls.find(
      ([input]) => new URL(String(input), "http://api.test").pathname === "/profiles/preview",
    );
    expect(previewCall).toBeDefined();
    expect(JSON.parse(String(previewCall?.[1]?.body))).toMatchObject({
      limit: 12,
      draft: { fields: ["computer-science"] },
    });
  });

  it("sends a visible paper correction back as a refinement", async () => {
    const user = userEvent.setup();
    const selected = { ...emptyDraft, fields: ["computer-science"] };
    const mock = vi.fn((input: string, _init?: RequestInit) => {
      const path = new URL(input, "http://api.test").pathname;
      if (path === "/fields") return Promise.resolve(jsonOk(makeFields()));
      if (path === "/profiles/options") return Promise.resolve(jsonOk(options));
      if (path === "/profiles/preview") return Promise.resolve(jsonOk(response(selected)));
      if (path === "/profiles/refine") return Promise.resolve(jsonOk(response(selected)));
      return Promise.reject(new Error(`unhandled path ${path}`));
    });
    vi.stubGlobal("fetch", mock);
    renderProfile();

    await user.click(await screen.findByRole("button", { name: "Computer Science" }));
    await user.click(screen.getByRole("button", { name: "Show me my feed" }));
    await user.click(await screen.findByRole("button", { name: "Not interested" }));

    await waitFor(() => {
      expect(
        mock.mock.calls.some(
          ([input]) =>
            new URL(String(input), "http://api.test").pathname === "/profiles/refine",
        ),
      ).toBe(true);
    });
    const refineCall = mock.mock.calls.find(
      ([input]) => new URL(String(input), "http://api.test").pathname === "/profiles/refine",
    );
    expect(JSON.parse(String(refineCall?.[1]?.body))).toMatchObject({
      refinements: [
        {
          action: "not_interested",
          paper_id: "paper-1",
          interest_key: "field:computer-science",
        },
      ],
    });
  });

  it("finds a paper and carries it into the profile draft", async () => {
    const user = userEvent.setup();
    const example = makeSummary({ id: "example-1", title: "A concrete anchor paper" });
    const mock = vi.fn((input: string, init?: RequestInit) => {
      const url = new URL(input, "http://api.test");
      if (url.pathname === "/fields") return Promise.resolve(jsonOk(makeFields()));
      if (url.pathname === "/profiles/options") return Promise.resolve(jsonOk(options));
      if (url.pathname === "/search") {
        return Promise.resolve(
          jsonOk({
            query: url.searchParams.get("q"),
            count: 1,
            limit: 5,
            results: [{ rank: 1, paper: example }],
          }),
        );
      }
      if (url.pathname === "/profiles/preview") {
        const body = JSON.parse(String(init?.body)) as { draft: ProfileDraft };
        return Promise.resolve(jsonOk(response(body.draft)));
      }
      return Promise.reject(new Error(`unhandled path ${url.pathname}`));
    });
    vi.stubGlobal("fetch", mock);
    renderProfile();

    const search = await screen.findByRole("search", { name: "Find example papers" });
    await user.type(within(search).getByRole("searchbox"), "graph recommendation");
    await user.click(within(search).getByRole("button", { name: "Find papers" }));
    await user.click(await screen.findByRole("button", { name: "Use this paper" }));

    expect(screen.getByRole("list", { name: "Chosen example papers" })).toHaveTextContent(
      "A concrete anchor paper",
    );
    await user.click(screen.getByRole("button", { name: "Show me my feed" }));

    await screen.findByRole("link", { name: "A useful recommendation paper" });
    const previewCall = mock.mock.calls.find(
      ([input]) => new URL(String(input), "http://api.test").pathname === "/profiles/preview",
    );
    expect(JSON.parse(String(previewCall?.[1]?.body))).toMatchObject({
      draft: {
        example_papers: [
          {
            paper_id: "example-1",
            importance: "interested",
            label: "A concrete anchor paper",
          },
        ],
      },
    });
  });
});
