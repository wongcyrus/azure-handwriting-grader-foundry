import { useState } from "react";
import { ApiError, request } from "./api";
import type { Exam, OfflineJob, OfflineJobList, OfflineResult } from "./types";

const states: Record<string, string> = {
  PENDING_DISPATCH: "Requested - not started",
  ASSIGNED_WITHOUT_DELIVERY: "Assigned - delivery not confirmed",
  READY_FOR_VALIDATION: "Ready for offline validation",
  VALIDATION_CLAIMED: "Reserved for offline validation",
  VALIDATION_RUNNING: "Offline validation running",
  VALIDATION_CLAIM_EXPIRED: "Validation reservation expired",
  DELIVERY_SENDING: "Delivery attempt in progress",
  DELIVERY_SEND_EXPIRED: "Delivery outcome needs recovery",
  DELIVERY_RETRY_WAIT: "Waiting before another delivery attempt",
  DELIVERY_RETRY_READY: "Eligible for another delivery attempt",
  DELIVERY_REVIEW: "Operator delivery review required",
  QUARANTINED: "Operator integrity review required",
  STALE: "Held after input changes",
  STALE_INPUTS: "Inputs changed - old check cannot run",
  CANCELLED: "Cancelled",
  VALIDATED: "Offline input validation passed",
  VALIDATED_HISTORICAL: "Historical validation - inputs have changed",
};
type Pending = { checkpoint_id: string; request_id: string; confirmed: true };

export function OfflineJobs({
  exam,
  etag,
  token,
  busy,
  unsaved,
  onBusy,
  onAdopt,
  onError,
}: {
  exam: Exam;
  etag: string;
  token: string;
  busy: boolean;
  unsaved: boolean;
  onBusy: (value: boolean) => void;
  onAdopt: (snapshot: { value: Exam; etag: string }) => void;
  onError: (message: string) => void;
}) {
  const [confirmed, setConfirmed] = useState(false);
  const [pending, setPending] = useState<Pending | null>(null);
  const [jobs, setJobs] = useState<OfflineJob[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [listed, setListed] = useState(false);
  const [selected, setSelected] = useState<OfflineJob | null>(null);
  const [result, setResult] = useState<OfflineResult | null>(null);
  const [conflicted, setConflicted] = useState(false);
  const [notice, setNotice] = useState("");
  const base = `/api/exams/${exam.id}/jobs`;
  const blocked = busy || unsaved || conflicted;

  function observe(version: number) {
    if (version !== exam.version) {
      setConflicted(true);
      setConfirmed(false);
    }
  }

  async function perform(operation: () => Promise<void>) {
    onBusy(true);
    onError("");
    try {
      await operation();
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setConflicted(true);
        setConfirmed(false);
      }
      onError(
        reason instanceof Error
          ? reason.message
          : "Offline check request failed.",
      );
    } finally {
      onBusy(false);
    }
  }

  async function list(append = false) {
    const query =
      append && cursor ? `?cursor=${encodeURIComponent(cursor)}` : "";
    const { value } = await request<OfflineJobList>(base + query, token);
    observe(value.exam_version);
    setJobs(
      append && value.exam_version === exam.version
        ? [
            ...jobs,
            ...value.items.filter(
              (item) => !jobs.some((job) => job.job_id === item.job_id),
            ),
          ]
        : value.items,
    );
    setCursor(value.next_cursor);
    setListed(true);
    setSelected(null);
    setResult(null);
  }

  async function submit() {
    let body = pending;
    if (!body) {
      const { value } = await request<{ checkpoint_id: string }>(
        `/api/exams/${exam.id}/offline-inputs`,
        token,
        { method: "POST", etag, body: { confirmed: true } },
      );
      body = {
        checkpoint_id: value.checkpoint_id,
        request_id: crypto.randomUUID(),
        confirmed: true,
      };
      setPending(body);
    }
    await request(base, token, { method: "POST", etag, body });
    setPending(null);
    setConfirmed(false);
    setNotice("Offline check requested. No worker or AI call was started.");
    await list();
  }

  async function inspect(job: OfflineJob) {
    setSelected(null);
    setResult(null);
    const { value } = await request<OfflineJob>(`${base}/${job.job_id}`, token);
    observe(value.exam_version);
    setSelected(value);
    if (value.result_available) {
      const response = await request<OfflineResult>(
        `${base}/${job.job_id}/result`,
        token,
      );
      if (response.etag !== etag) setConflicted(true);
      setResult(response.value);
    }
  }

  async function cancel() {
    if (
      !selected ||
      !window.confirm(
        "Cancel this offline check? This does not change exam approvals.",
      )
    )
      return;
    await request(`${base}/${selected.job_id}/cancel`, token, {
      method: "POST",
      etag,
      body: { confirmed: true },
    });
    setNotice("Offline check cancelled.");
    await list();
  }

  async function reload() {
    if (
      unsaved &&
      !window.confirm("Discard unsaved edits and reload the current exam?")
    )
      return;
    const next = await request<Exam>(`/api/exams/${exam.id}`, token);
    setConflicted(false);
    setConfirmed(false);
    setPending(null);
    setSelected(null);
    setResult(null);
    onAdopt(next);
  }

  return (
    <section className="card" aria-label="Offline input checks">
      <h2>Offline input checks</h2>
      <p>
        Checks approved files and geometry only. It does not read handwriting,
        grade answers or call AI. No worker is running in this local demo.
        Refreshing or inspecting a check never starts work.
      </p>
      {unsaved && (
        <p>
          Save or discard local edits before requesting or cancelling a check.
        </p>
      )}
      <label>
        <input
          type="checkbox"
          checked={confirmed}
          disabled={blocked || exam.state !== "REGIONS_REVIEWED"}
          onChange={(event) => setConfirmed(event.target.checked)}
        />
        I request an offline check of the saved, approved inputs
      </label>
      <button
        disabled={blocked || !confirmed || exam.state !== "REGIONS_REVIEWED"}
        onClick={() => void perform(submit)}
      >
        {pending ? "Retry same offline request" : "Request offline check"}
      </button>
      {pending && (
        <p>
          The request may not have been acknowledged. Refresh checks to inspect
          the outcome; retry uses the same request identity, not a new job.
        </p>
      )}
      <button disabled={busy} onClick={() => void perform(() => list())}>
        Refresh offline checks
      </button>
      {conflicted && (
        <div className="warning">
          <p>
            The exam changed. Local edits are preserved. Reload the current exam
            before another request or cancellation; review the latest approvals
            again.
          </p>
          <button disabled={busy} onClick={() => void perform(reload)}>
            Reload current exam for checks
          </button>
        </div>
      )}
      <p aria-live="polite">{notice}</p>
      {listed && jobs.length === 0 && (
        <p>No offline checks requested for this exam.</p>
      )}
      {jobs.length > 0 && (
        <table>
          <caption>Owned offline checks</caption>
          <thead>
            <tr>
              <th>Check</th>
              <th>Status</th>
              <th>Input version</th>
              <th>Details</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.job_id}>
                <td>
                  <small>{job.job_id}</small>
                </td>
                <td>{states[job.state] || job.state}</td>
                <td>{job.source_exam_version}</td>
                <td>
                  <button
                    disabled={busy}
                    onClick={() => void perform(() => inspect(job))}
                    aria-label={`Inspect check ${job.job_id}`}
                  >
                    Inspect check
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {cursor && (
        <button disabled={busy} onClick={() => void perform(() => list(true))}>
          More offline checks
        </button>
      )}
      {selected && (
        <div aria-label="Offline check details">
          <h3>Check details</h3>
          <p>
            {result && conflicted
              ? states.VALIDATED_HISTORICAL
              : states[selected.state] || selected.state}
          </p>
          {(selected.state === "VALIDATED_HISTORICAL" ||
            (conflicted && !!result) ||
            !selected.current_job_scope) && (
            <p className="warning">
              This check is not authority for the current inputs or grading.
              Historical results describe the old saved input version only.
            </p>
          )}
          {!selected.result_available && <p>No committed validation result.</p>}
          <button
            disabled={
              blocked ||
              selected.result_available ||
              selected.state === "CANCELLED"
            }
            onClick={() => void perform(cancel)}
          >
            Cancel offline check
          </button>
          {result && (
            <div>
              <h3>Recorded offline validation</h3>
              <p>
                Input version {selected.source_exam_version}; checked at{" "}
                {result.validated_at}. This is not a grade or proof of scan
                identity/orientation.
              </p>
              <dl>
                <dt>Present students</dt>
                <dd>{result.summary.students}</dd>
                <dt>Absent students</dt>
                <dd>{result.summary.absent}</dd>
                <dt>PDF pages</dt>
                <dd>{result.summary.pdf_pages}</dd>
                <dt>Rubric total marks (not awarded scores)</dt>
                <dd>{result.summary.total_marks}</dd>
              </dl>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
