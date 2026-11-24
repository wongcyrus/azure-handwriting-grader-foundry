import { useEffect, useState } from "react";
import { ApiError, request } from "./api";
import type { Exam, InputKind } from "./types";

export function InputSetup({
  exam,
  etag,
  token,
  busy,
  onBusy,
  onAdopt,
  onError,
  onDirty,
}: {
  exam: Exam;
  etag: string;
  token: string;
  busy: boolean;
  onBusy: (value: boolean) => void;
  onAdopt: (snapshot: { value: Exam; etag: string }) => void;
  onError: (message: string) => void;
  onDirty: (value: boolean) => void;
}) {
  const [settings, setSettings] = useState(exam.settings);
  const [settingsDirty, setSettingsDirty] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [attendanceConfirmed, setAttendanceConfirmed] = useState(false);
  const [conflicted, setConflicted] = useState(false);
  useEffect(() => {
    onDirty(settingsDirty);
    return () => onDirty(false);
  }, [settingsDirty, onDirty]);

  async function mutate(path: string, method: string, body?: unknown) {
    onBusy(true);
    onError("");
    try {
      onAdopt(
        await request<Exam>(`/api/exams/${exam.id}${path}`, token, {
          method,
          body,
          etag,
        }),
      );
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409)
        setConflicted(true);
      onError(
        reason instanceof Error ? reason.message : "Input operation failed.",
      );
    } finally {
      onBusy(false);
    }
  }
  const preflight = exam.preflight;
  const hasAttendance = !!exam.artifacts.attendance;
  return (
    <section className="card">
      <h2>Input setup and review</h2>
      <p>
        Upload synthetic PDF scans and XLSX roster/rubric files only. The roster
        uses ID, NAME, CLASS on the selected sheet. The rubric uses the standard
        Marking Scheme sheet. Optional CSV attendance must cover every roster
        ID; missing scans never imply absence.
      </p>
      {exam.state === "SETUP" && (
        <>
          <fieldset disabled={busy}>
            <legend>Scan layout</legend>
            <label>
              Pages per student
              <select
                value={settings.pages_per_student}
                onChange={(event) => {
                  setSettings({
                    ...settings,
                    pages_per_student: Number(event.target.value),
                  });
                  setSettingsDirty(true);
                }}
              >
                {Array.from({ length: 20 }, (_, index) => (
                  <option key={index} value={index + 1}>
                    {index + 1}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Roster sheet
              <input
                maxLength={31}
                value={settings.roster_sheet}
                onChange={(event) => {
                  setSettings({
                    ...settings,
                    roster_sheet: event.target.value,
                  });
                  setSettingsDirty(true);
                }}
              />
            </label>
            <label>
              <input
                type="checkbox"
                checked={settings.scan_order_confirmed}
                onChange={(event) => {
                  setSettings({
                    ...settings,
                    scan_order_confirmed: event.target.checked,
                  });
                  setSettingsDirty(true);
                }}
              />
              I confirmed scan order
            </label>
            <label>
              <input
                type="checkbox"
                checked={settings.same_layout_for_all}
                onChange={(event) => {
                  setSettings({
                    ...settings,
                    same_layout_for_all: event.target.checked,
                  });
                  setSettingsDirty(true);
                }}
              />
              All scripts use the same layout
            </label>
            <button
              disabled={!settingsDirty}
              onClick={() => void mutate("/settings", "PUT", settings)}
            >
              Save input settings
            </button>
          </fieldset>
          {settingsDirty && (
            <p role="status">
              Unsaved input settings. Save before uploading or reviewing.
            </p>
          )}
          {(["scans", "roster", "rubric", "attendance"] as InputKind[]).map(
            (kind) => (
              <label key={kind}>
                Upload {kind}
                <input
                  type="file"
                  accept={
                    kind === "scans"
                      ? ".pdf"
                      : kind === "attendance"
                        ? ".csv"
                        : ".xlsx"
                  }
                  disabled={busy || settingsDirty}
                  onChange={(event) => {
                    const file = event.target.files?.[0];
                    if (!file) return;
                    if (file.size > 10 * 1024 * 1024) {
                      onError("Local uploads are limited to 10 MiB.");
                      return;
                    }
                    void mutate(`/artifacts/${kind}`, "POST", file);
                  }}
                />
                {exam.artifacts[kind] && (
                  <small>
                    {kind} uploaded: {exam.artifacts[kind]!.size} bytes, SHA-256{" "}
                    {exam.artifacts[kind]!.sha256}
                  </small>
                )}
              </label>
            ),
          )}
          <button
            disabled={
              busy ||
              settingsDirty ||
              !settings.scan_order_confirmed ||
              !settings.same_layout_for_all ||
              !["scans", "roster", "rubric"].every(
                (kind) => kind in exam.artifacts,
              )
            }
            onClick={() => void mutate("/review", "POST")}
          >
            Validate inputs for review
          </button>
        </>
      )}
      {preflight && (
        <>
          <p>
            {preflight.summary.students} present, {preflight.summary.absent}{" "}
            absent; {preflight.summary.pdf_pages} PDF pages;{" "}
            {preflight.summary.total_marks} rubric marks available. Absence is a
            status, not a zero score.
          </p>
          <h3>Complete roster and attendance</h3>
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Class</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {preflight.attendance_review?.map((row) => (
                <tr key={row.id}>
                  <td>{row.id}</td>
                  <td>{row.name}</td>
                  <td>{row.class}</td>
                  <td>{row.status}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <h3>Rubric criteria</h3>
          <table>
            <thead>
              <tr>
                <th>Question</th>
                <th>Text</th>
                <th>Criteria</th>
                <th>Marks</th>
              </tr>
            </thead>
            <tbody>
              {preflight.rubric_review?.map((row) => (
                <tr key={row.question_number}>
                  <td>{row.question_number}</td>
                  <td>{row.question_text}</td>
                  <td>{row.marking_scheme}</td>
                  <td>{row.marks}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {(!preflight.rubric_review || !preflight.attendance_review) && (
            <p>
              Legacy review has no criteria preview. Change inputs and
              revalidate before approval.
            </p>
          )}
        </>
      )}
      {exam.state === "WAITING_FOR_INPUT_REVIEW" && (
        <>
          <label>
            <input
              type="checkbox"
              disabled={busy}
              checked={confirmed}
              onChange={(event) => setConfirmed(event.target.checked)}
            />
            I reviewed the roster, rubric and scan settings
          </label>
          {hasAttendance && (
            <label>
              <input
                type="checkbox"
                disabled={busy}
                checked={attendanceConfirmed}
                onChange={(event) =>
                  setAttendanceConfirmed(event.target.checked)
                }
              />
              I separately confirm the present/absent attendance list
            </label>
          )}
          <button
            disabled={
              busy ||
              !confirmed ||
              !preflight?.rubric_review?.length ||
              !preflight?.attendance_review?.length ||
              (hasAttendance && !attendanceConfirmed)
            }
            onClick={() =>
              void mutate("/approvals", "POST", {
                snapshot_sha256: exam.snapshot_sha256,
                confirmed,
                attendance_confirmed: attendanceConfirmed,
              })
            }
          >
            Approve input snapshot
          </button>
        </>
      )}
      {exam.state !== "SETUP" && (
        <button
          disabled={busy}
          onClick={() => {
            if (
              window.confirm(
                "Changing inputs invalidates current input, attendance and region approvals. Continue?",
              )
            )
              void mutate("/settings", "PUT", exam.settings);
          }}
        >
          Change inputs (invalidate approvals)
        </button>
      )}
      {conflicted && (
        <button
          disabled={busy}
          onClick={async () => {
            if (
              !window.confirm(
                "Discard unsaved input settings and reload the current snapshot?",
              )
            )
              return;
            onBusy(true);
            try {
              const next = await request<Exam>(`/api/exams/${exam.id}`, token);
              setSettings(next.value.settings);
              setSettingsDirty(false);
              setConflicted(false);
              onAdopt(next);
            } catch (reason) {
              onError(
                reason instanceof Error ? reason.message : "Reload failed.",
              );
            } finally {
              onBusy(false);
            }
          }}
        >
          Reload inputs (discard unsaved settings)
        </button>
      )}
    </section>
  );
}
