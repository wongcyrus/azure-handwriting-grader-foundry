export interface Box {
  x: number;
  y: number;
  width: number;
  height: number;
  label: string;
}

export interface TemplatePage {
  index: number;
  width: number;
  height: number;
  artifact_id: string;
  sha256: string;
}

export interface Draft {
  annotations: Record<string, Box[]>;
  reviewed_pages: number[];
}

export interface Regions extends Draft {
  pages: TemplatePage[];
  review_sha256: string;
  question_labels: string[];
  revision: number;
}

export interface Exam {
  id: string;
  title: string;
  state: string;
  snapshot_sha256: string;
  current_region_approval: string | null;
  regions: Regions | null;
  version: number;
  settings: Settings;
  artifacts: Partial<
    Record<InputKind, { id: string; sha256: string; size: number }>
  >;
  preflight: {
    summary: {
      students: number;
      absent: number;
      pdf_pages: number;
      total_marks: number;
    };
    attendance_review?: {
      id: string;
      name: string;
      class: string;
      status: string;
    }[];
    rubric_review?: {
      question_number: string;
      question_text: string;
      marking_scheme: string;
      marks: number;
    }[];
  } | null;
}

export type InputKind = "scans" | "roster" | "rubric" | "attendance";
export interface Settings {
  pages_per_student: number;
  scan_order_confirmed: boolean;
  same_layout_for_all: boolean;
  roster_sheet: string;
}

export interface ExamList {
  exams: { id: string; title: string; state: string; version: number }[];
  next_cursor: string | null;
}
