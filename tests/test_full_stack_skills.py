from __future__ import annotations

from pathlib import Path

from zerocode import skills


def test_full_stack_skills_include_core_expertise_and_detect_project_patterns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(skills, "config_dir", lambda: tmp_path / "config")
    project_skills = tmp_path / ".zerocode" / "skills"
    project_skills.mkdir(parents=True)
    (project_skills / "fabric-react_frontend.md").write_text(
        "# React frontend\nComponents and user interfaces.", encoding="utf-8"
    )
    (project_skills / "fabric-sql_database.md").write_text(
        "# SQL database\nRelational data and migrations.", encoding="utf-8"
    )
    (project_skills / "fabric-video_storytelling.md").write_text(
        "# Video storytelling\nNarrative structure.", encoding="utf-8"
    )
    (tmp_path / "package.json").write_text(
        '{"dependencies":{"next":"latest","react":"latest","@supabase/supabase-js":"latest"}}',
        encoding="utf-8",
    )

    selected = skills.select_full_stack_skills(tmp_path, "Build the frontend and database")

    assert {"ultra-dev", "cyber-sec", "sys-tech", "review", "perf", "sec-hardening"} <= set(selected)
    assert "fabric-react_frontend" in selected
    assert "fabric-sql_database" in selected
    assert "fabric-video_storytelling" not in selected
    assert len(selected) <= 14
