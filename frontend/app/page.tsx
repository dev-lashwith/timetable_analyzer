"use client";

import { useState } from "react";

import ArchiveWorkflow from "./archive-workflow";
import LegacyPage from "./legacy-page";

export default function Home() {
  const [view, setView] = useState<"archive" | "manual">("archive");
  return (
    <>
      <nav className="workflow-nav" aria-label="Timetable tools">
        <button className={view === "archive" ? "is-active" : ""} onClick={() => setView("archive")}>Department archive</button>
        <button className={view === "manual" ? "is-active" : ""} onClick={() => setView("manual")}>Manual crop editor</button>
      </nav>
      {view === "archive" ? <ArchiveWorkflow /> : <LegacyPage />}
    </>
  );
}
