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
}

export interface ExamList {
  exams: { id: string; title: string; state: string; version: number }[];
  next_cursor: string | null;
}
