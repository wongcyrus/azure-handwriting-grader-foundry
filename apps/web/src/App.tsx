import { useEffect, useState } from "react";
import type { FormEvent, KeyboardEvent, PointerEvent } from "react";
import { ApiError, request } from "./api";
import { drawnBox, imagePoint, movedBox, validBox } from "./geometry";
import type { Point } from "./geometry";
import type { Box, Draft, Exam } from "./types";

type Snapshot = { value: Exam; etag: string };
const copyDraft = (exam: Exam): Draft | null =>
  exam.regions
    ? structuredClone({
        annotations: exam.regions.annotations,
        reviewed_pages: exam.regions.reviewed_pages,
      })
    : null;

export function App() {
  const [tokenInput, setTokenInput] = useState("");
  const [examInput, setExamInput] = useState("");
  const [token, setToken] = useState("");
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [pageIndex, setPageIndex] = useState(0);
  const [selected, setSelected] = useState<number | null>(null);
  const [label, setLabel] = useState("ID");
  const [zoom, setZoom] = useState(0.5);
  const [dirty, setDirty] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState<Snapshot | null>(null);
  const [image, setImage] = useState<{ id: string; url: string } | null>(null);
  const [loadedImage, setLoadedImage] = useState("");
  const [drag, setDrag] = useState<{ start: Point; end: Point } | null>(null);
  const exam = snapshot?.value;
  const regions = exam?.regions;
  const page = regions?.pages[pageIndex];
  const boxes = draft?.annotations[String(pageIndex)] || [];
  const imageReady =
    !!page &&
    image?.id === page.artifact_id &&
    loadedImage === page.artifact_id;
  const selectedBox = selected === null ? undefined : boxes[selected];

  function adopt(next: Snapshot) {
    setSnapshot(next);
    setPageIndex((index) =>
      index < (next.value.regions?.pages.length || 0) ? index : 0,
    );
    setDraft(copyDraft(next.value));
    setDirty(false);
    setConfirmed(false);
    setSelected(null);
    setConflict(null);
    setError("");
  }

  useEffect(() => {
    if (!page || !exam || !token) return;
    setLoadedImage("");
    const controller = new AbortController();
    let url = "";
    let active = true;
    fetch(`/api/exams/${exam.id}/regions/pages/${page.index}`, {
      headers: { Authorization: `Bearer ${token}` },
      cache: "no-store",
      signal: controller.signal,
    })
      .then(async (response) => {
        if (!response.ok)
          throw new Error(
            "Page preview unavailable. Refresh the current inputs.",
          );
        return response.blob();
      })
      .then((blob) => {
        if (!active) return;
        url = URL.createObjectURL(blob);
        setImage({ id: page.artifact_id, url });
      })
      .catch((reason: Error) => {
        if (active) setError(reason.message);
      });
    return () => {
      active = false;
      controller.abort();
      if (url) URL.revokeObjectURL(url);
    };
  }, [page?.artifact_id, exam?.id, token]);

  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  async function connect(event: FormEvent) {
    event.preventDefault();
    if (dirty && !window.confirm("Discard unsaved edits and load this exam?"))
      return;
    if (tokenInput.includes(".")) {
      setError("Use a synthetic development token, not a real identity token.");
      return;
    }
    setBusy(true);
    try {
      const next = await request<Exam>(
        `/api/exams/${examInput.trim()}`,
        tokenInput,
      );
      setToken(tokenInput);
      setTokenInput("");
      setPageIndex(0);
      adopt(next);
    } catch (reason) {
      setError(
        reason instanceof Error ? reason.message : "Could not load exam.",
      );
    } finally {
      setBusy(false);
    }
  }

  async function action(kind: "prepare" | "save" | "approve") {
    if (!exam || !snapshot) return;
    setBusy(true);
    setError("");
    try {
      const suffix =
        kind === "prepare"
          ? "/prepare"
          : kind === "approve"
            ? "/approvals"
            : "";
      const body =
        kind === "save"
          ? { snapshot_sha256: exam.snapshot_sha256, ...draft }
          : kind === "approve"
            ? {
                snapshot_sha256: exam.snapshot_sha256,
                regions_sha256: regions?.review_sha256,
                confirmed,
              }
            : undefined;
      adopt(
        await request<Exam>(`/api/exams/${exam.id}/regions${suffix}`, token, {
          method: kind === "save" ? "PUT" : "POST",
          body,
          etag: snapshot.etag,
        }),
      );
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        try {
          setConflict(await request<Exam>(`/api/exams/${exam.id}`, token));
        } catch {
          setError(
            "The exam changed and the latest snapshot could not be loaded. Your edits remain.",
          );
        }
      }
      setError(
        reason instanceof Error
          ? reason.message
          : "Request failed; your edits remain.",
      );
    } finally {
      setBusy(false);
    }
  }

  function changeBoxes(next: Box[], nextSelected = selected) {
    if (!draft) return;
    setDraft({
      annotations: { ...draft.annotations, [String(pageIndex)]: next },
      reviewed_pages: draft.reviewed_pages.filter(
        (index) => index !== pageIndex,
      ),
    });
    setSelected(nextSelected);
    setDirty(true);
    setConfirmed(false);
  }

  function updateBox(next: Box) {
    if (!page || selected === null) return;
    if (!validBox(next, page)) {
      setError("Use whole pixels and keep the box within the rendered page.");
      return;
    }
    setError("");
    changeBoxes(boxes.map((box, index) => (index === selected ? next : box)));
  }

  function pointer(event: PointerEvent<SVGSVGElement>): Point {
    return imagePoint(
      { x: event.clientX, y: event.clientY },
      event.currentTarget.getBoundingClientRect(),
      page!,
    );
  }

  function keyboard(event: KeyboardEvent<SVGSVGElement>) {
    if (busy || !selectedBox || !page) return;
    if (event.key === "Delete" || event.key === "Backspace") {
      event.preventDefault();
      changeBoxes(
        boxes.filter((_, index) => index !== selected),
        null,
      );
      return;
    }
    const delta: Record<string, [number, number]> = {
      ArrowLeft: [-1, 0],
      ArrowRight: [1, 0],
      ArrowUp: [0, -1],
      ArrowDown: [0, 1],
    };
    if (delta[event.key]) {
      event.preventDefault();
      const [dx, dy] = delta[event.key];
      const step = event.shiftKey ? 10 : 1;
      updateBox(movedBox(selectedBox, dx * step, dy * step, page));
    }
  }

  const ghost =
    page && drag ? drawnBox(drag.start, drag.end, page, label) : null;
  const canReapply =
    !!conflict?.value.regions &&
    !!regions &&
    conflict.value.snapshot_sha256 === exam?.snapshot_sha256 &&
    conflict.value.regions.pages.every(
      (item, index) => item.sha256 === regions.pages[index]?.sha256,
    ) &&
    conflict.value.regions.pages.length === regions.pages.length;
  const reviewedAll =
    !!regions &&
    regions.pages.every((item) => draft?.reviewed_pages.includes(item.index));

  return (
    <main>
      <header>
        <h1>Teacher region review</h1>
        <p className="warning">
          Local synthetic demo only. No real tokens or student data. Production
          sign-in is not implemented.
        </p>
      </header>
      {!exam ? (
        <form onSubmit={connect} className="card">
          <label>
            Exam ID
            <input
              required
              value={examInput}
              onChange={(event) => setExamInput(event.target.value)}
              disabled={busy}
            />
          </label>
          <label>
            Synthetic development token
            <input
              required
              type="password"
              autoComplete="off"
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
              disabled={busy}
            />
          </label>
          <button disabled={busy}>Load exam</button>
        </form>
      ) : (
        <>
          <section className="card">
            <h2>{exam.title}</h2>
            <p role="status">
              {dirty
                ? "Unsaved edits - not approved"
                : exam.current_region_approval
                  ? "Saved region layout approved"
                  : "Region approval pending"}
            </p>
            <p>
              The first present student's script is a common-layout template.
              This does not verify every student's orientation, identity or scan
              sequence. Approval does not start grading.
            </p>
            <button
              disabled={busy}
              onClick={() => {
                if (
                  dirty &&
                  !window.confirm("Discard unsaved edits and disconnect?")
                )
                  return;
                setToken("");
                setTokenInput("");
                setSnapshot(null);
                setDraft(null);
                setDirty(false);
                setConfirmed(false);
                setConflict(null);
                setImage(null);
              }}
            >
              Disconnect
            </button>
            {!regions && (
              <button
                disabled={busy || exam.state !== "INPUTS_REVIEWED"}
                onClick={() => void action("prepare")}
              >
                Prepare template
              </button>
            )}
            {!regions && exam.state !== "INPUTS_REVIEWED" && (
              <p>Complete input review before preparing the template.</p>
            )}
          </section>
          {regions && draft && page && (
            <section className="editor">
              <div className="card">
                <nav aria-label="Template pages">
                  {regions.pages.map((item) => (
                    <button
                      key={item.index}
                      aria-pressed={pageIndex === item.index}
                      disabled={busy}
                      onClick={() => {
                        setPageIndex(item.index);
                        setSelected(null);
                        setDrag(null);
                      }}
                    >
                      Page {item.index + 1}:{" "}
                      {draft.reviewed_pages.includes(item.index)
                        ? "reviewed"
                        : "needs review"}
                    </button>
                  ))}
                </nav>
                <label>
                  Zoom
                  <select
                    value={zoom}
                    onChange={(event) => setZoom(Number(event.target.value))}
                  >
                    {[0.25, 0.5, 1, 1.5, 2].map((value) => (
                      <option key={value} value={value}>
                        {value * 100}%
                      </option>
                    ))}
                  </select>
                </label>
                <p>
                  {page.width} x {page.height} canonical pixels, top-left
                  origin. Drag to draw; select a box and use arrow keys (Shift:
                  10 pixels) or Delete.
                </p>
                <div className="viewport">
                  <div
                    className="sheet"
                    style={{
                      width: page.width * zoom,
                      height: page.height * zoom,
                    }}
                  >
                    {image?.id === page.artifact_id && (
                      <img
                        alt={`Template page ${pageIndex + 1}`}
                        src={image.url}
                        onLoad={() => setLoadedImage(page.artifact_id)}
                      />
                    )}
                    <svg
                      role="application"
                      aria-label="Page region canvas"
                      tabIndex={0}
                      viewBox={`0 0 ${page.width} ${page.height}`}
                      onKeyDown={keyboard}
                      onPointerDown={(event) => {
                        if (busy || !imageReady || event.button !== 0) return;
                        const start = pointer(event);
                        event.currentTarget.setPointerCapture(event.pointerId);
                        setDrag({ start, end: start });
                      }}
                      onPointerMove={(event) => {
                        if (drag) setDrag({ ...drag, end: pointer(event) });
                      }}
                      onPointerUp={(event) => {
                        if (!drag || busy) return;
                        const box = drawnBox(
                          drag.start,
                          pointer(event),
                          page,
                          label,
                        );
                        if (box) changeBoxes([...boxes, box], boxes.length);
                        setDrag(null);
                        event.currentTarget.releasePointerCapture(
                          event.pointerId,
                        );
                      }}
                      onPointerCancel={() => setDrag(null)}
                    >
                      {boxes.map((box, index) => (
                        <g
                          key={index}
                          data-box={index}
                          onPointerDown={(event) => {
                            event.stopPropagation();
                            setSelected(index);
                          }}
                        >
                          <rect
                            x={box.x}
                            y={box.y}
                            width={box.width}
                            height={box.height}
                            className={selected === index ? "selected" : ""}
                          />
                          <text x={box.x + 2} y={box.y + 14}>
                            {box.label}
                          </text>
                        </g>
                      ))}
                      {ghost && (
                        <rect
                          className="ghost"
                          x={ghost.x}
                          y={ghost.y}
                          width={ghost.width}
                          height={ghost.height}
                        />
                      )}
                    </svg>
                  </div>
                </div>
                {!imageReady && <p>Loading protected page preview...</p>}
                <label>
                  <input
                    type="checkbox"
                    disabled={busy || !imageReady}
                    checked={draft.reviewed_pages.includes(pageIndex)}
                    onChange={(event) => {
                      setDraft({
                        ...draft,
                        reviewed_pages: event.target.checked
                          ? [...draft.reviewed_pages, pageIndex]
                          : draft.reviewed_pages.filter(
                              (index) => index !== pageIndex,
                            ),
                      });
                      setDirty(true);
                      setConfirmed(false);
                    }}
                  />
                  I reviewed page {pageIndex + 1} and its boxes
                </label>
              </div>
              <aside className="card">
                <h2>Boxes</h2>
                <label>
                  New box label
                  <select
                    value={label}
                    onChange={(event) => setLabel(event.target.value)}
                    disabled={busy}
                  >
                    {["ID", "NAME", "CLASS", ...regions.question_labels].map(
                      (value) => (
                        <option key={value}>{value}</option>
                      ),
                    )}
                  </select>
                </label>
                <button
                  disabled={busy || !imageReady}
                  onClick={() =>
                    changeBoxes(
                      [
                        ...boxes,
                        {
                          x: 0,
                          y: 0,
                          width: Math.min(20, page.width),
                          height: Math.min(20, page.height),
                          label,
                        },
                      ],
                      boxes.length,
                    )
                  }
                >
                  Add box with keyboard
                </button>
                <ul>
                  {boxes.map((box, index) => (
                    <li key={index}>
                      <button
                        aria-pressed={selected === index}
                        onClick={() => setSelected(index)}
                      >
                        Select {box.label} box {index + 1}
                      </button>
                    </li>
                  ))}
                </ul>
                {selectedBox && (
                  <fieldset disabled={busy}>
                    <legend>Selected box</legend>
                    <label>
                      Label
                      <input
                        value={selectedBox.label}
                        onChange={(event) =>
                          updateBox({
                            ...selectedBox,
                            label: event.target.value,
                          })
                        }
                      />
                    </label>
                    {(["x", "y", "width", "height"] as const).map((key) => (
                      <label key={key}>
                        {key}
                        <input
                          aria-label={`Box ${key}`}
                          type="number"
                          step={1}
                          value={selectedBox[key]}
                          onChange={(event) => {
                            if (event.target.value !== "")
                              updateBox({
                                ...selectedBox,
                                [key]: Number(event.target.value),
                              });
                          }}
                        />
                      </label>
                    ))}
                    <button
                      onClick={() =>
                        changeBoxes(
                          boxes.filter((_, index) => index !== selected),
                          null,
                        )
                      }
                    >
                      Delete selected box
                    </button>
                  </fieldset>
                )}
                <button
                  disabled={busy || !dirty || !!conflict}
                  onClick={() => void action("save")}
                >
                  Save draft
                </button>
                <label>
                  <input
                    type="checkbox"
                    disabled={
                      busy ||
                      dirty ||
                      !reviewedAll ||
                      exam.state !== "WAITING_FOR_REGION_REVIEW"
                    }
                    checked={confirmed}
                    onChange={(event) => setConfirmed(event.target.checked)}
                  />
                  I approve this saved layout for scripts sharing it
                </label>
                <button
                  disabled={
                    busy ||
                    dirty ||
                    !confirmed ||
                    !reviewedAll ||
                    !!conflict ||
                    exam.state !== "WAITING_FOR_REGION_REVIEW"
                  }
                  onClick={() => void action("approve")}
                >
                  Approve regions
                </button>
              </aside>
            </section>
          )}
        </>
      )}
      {error && (
        <p role="alert" className="error">
          {error}
        </p>
      )}
      {conflict && (
        <section
          role="dialog"
          aria-label="Conflicting saved draft"
          className="card"
        >
          <h2>The server changed. Your local edits are preserved.</h2>
          <p>
            Reload discards local edits. Reapplying keeps your boxes against the
            latest ETag, but clears all page-review flags and requires a new
            explicit save and review.
          </p>
          <button onClick={() => adopt(conflict)}>
            Reload server draft (discard mine)
          </button>
          <button
            disabled={!canReapply || !draft}
            onClick={() => {
              if (!draft) return;
              setSnapshot(conflict);
              setDraft({ ...draft, reviewed_pages: [] });
              setDirty(true);
              setConfirmed(false);
              setConflict(null);
              setError("");
            }}
          >
            Reapply my boxes to latest (review again)
          </button>
        </section>
      )}
    </main>
  );
}
