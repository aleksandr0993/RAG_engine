from __future__ import annotations


class VisualAnalyzer:
    def check(self, task: str, artifacts: list[dict], criterion: dict) -> dict:
        if task == "has_extracted_text":
            for artifact in artifacts:
                if artifact["artifact_type"] not in {"pdf_page", "pdf_text_block"}:
                    continue
                text = (artifact.get("normalized_text") or "").strip()
                if len(text) >= 10:
                    return self._pass(artifact, task, note="text_detected")
            return self._fail_or_warn(task, criterion, note="no_text_detected")

        if task == "infer_dashboard_structure":
            score = 0
            anchor = None
            evidence = []
            for artifact in artifacts:
                text = (artifact.get("normalized_text") or "").lower()
                meta = artifact.get("metadata_json") or {}
                tags = meta.get("tags") or []
                region_kind = meta.get("region_kind")
                if artifact["artifact_type"] == "pdf_page_summary":
                    score += len(meta.get("signals") or [])
                    anchor = artifact if anchor is None else anchor
                if artifact["artifact_type"] in {"pdf_image_region", "datalens_image_region"}:
                    score += 2
                    anchor = artifact if anchor is None else anchor
                    evidence.append({"excerpt": text[:200], "region_kind": region_kind, "source": "image"})
                elif region_kind in {"filter", "metric", "chart", "table"}:
                    score += 2
                    anchor = artifact if anchor is None else anchor
                    evidence.append({"excerpt": text[:200], "region_kind": region_kind})
                elif tags:
                    score += len(tags)
                    anchor = artifact if anchor is None else anchor
                    evidence.append({"excerpt": text[:200], "tags": tags})
                elif any(token in text for token in ["дашборд", "kpi", "выруч", "метрик", "filter", "фильтр"]):
                    score += 1
                    anchor = artifact if anchor is None else anchor
                    evidence.append({"excerpt": text[:200]})
            if score >= 2 and anchor is not None:
                return {
                    "status": "pass",
                    "confidence": min(0.55 + score * 0.07, 0.93),
                    "anchor_position_idx": anchor.get("position_idx"),
                    "evidence": evidence[:5],
                    "metadata": {"task": task, "score": score, "mode": "heuristic", "source_stage": "visual"},
                }
            return self._fail_or_warn(task, criterion, note="dashboard_structure_weak")

        if task == "has_filter_signals":
            return self._find_signal(task, artifacts, criterion, signal="filter")

        if task == "has_metric_signals":
            return self._find_signal(task, artifacts, criterion, signal="metric")

        if task == "pdf_regions_extracted":
            regions = [a for a in artifacts if a["artifact_type"] == "pdf_region"]
            if regions:
                anchor = regions[0]
                return {
                    "status": "pass",
                    "confidence": 0.84,
                    "anchor_position_idx": anchor.get("position_idx"),
                    "evidence": [{"excerpt": (anchor.get("normalized_text") or "")[:200], "count": len(regions)}],
                    "metadata": {"task": task, "region_count": len(regions), "source_stage": "visual"},
                }
            return self._fail_or_warn(task, criterion, note="no_pdf_regions")

        if task == "pdf_page_images_saved":
            images = [a for a in artifacts if a["artifact_type"] == "pdf_page_image"]
            if images:
                anchor = images[0]
                return {
                    "status": "pass",
                    "confidence": 0.86,
                    "anchor_position_idx": anchor.get("position_idx"),
                    "evidence": [{"excerpt": anchor.get("normalized_text") or "", "count": len(images)}],
                    "metadata": {"task": task, "image_count": len(images), "source_stage": "visual"},
                }
            return self._fail_or_warn(task, criterion, note="no_pdf_page_images")

        if task == "pdf_image_regions_extracted":
            return self._count_artifacts(task, artifacts, criterion, "pdf_image_region", note="pdf_image_regions_present")

        if task == "pdf_overlays_saved":
            return self._count_artifacts(task, artifacts, criterion, "pdf_page_overlay", note="pdf_overlays_present")

        if task == "datalens_url_quality":
            for artifact in artifacts:
                if artifact["artifact_type"] != "datalens_url":
                    continue
                text = (artifact.get("normalized_text") or "").lower()
                if "datalens.yandex" in text:
                    return self._pass(artifact, task, note="datalens_domain_detected")
                if text.startswith("http://") or text.startswith("https://"):
                    return {
                        "status": "warn" if criterion["severity"] != "required" else "fail",
                        "confidence": 0.75,
                        "anchor_position_idx": artifact.get("position_idx"),
                        "evidence": [{"excerpt": text[:200]}],
                        "metadata": {"task": task, "note": "generic_url_only", "source_stage": "visual"},
                    }
            return self._fail_or_warn(task, criterion, note="no_url")

        if task == "datalens_capture_ready":
            for artifact in artifacts:
                if artifact["artifact_type"] != "datalens_capture_summary":
                    continue
                meta = artifact.get("metadata_json") or {}
                status = (meta.get("capture_status") or "").lower()
                if status in {"disabled", "skipped", "not_enabled"} or meta.get("capture_skipped"):
                    return {
                        "status": "pass",
                        "confidence": 1.0,
                        "anchor_position_idx": artifact.get("position_idx"),
                        "evidence": [{"excerpt": artifact.get("normalized_text") or ""}],
                        "metadata": {
                            "task": task,
                            "note": "browser_capture_skipped",
                            "capture_status": meta.get("capture_status"),
                            "source_stage": "visual",
                        },
                    }
                if meta.get("capture_available"):
                    return self._pass(artifact, task, note="capture_available")
                return {
                    "status": "warn" if criterion["severity"] != "required" else "fail",
                    "confidence": 0.5,
                    "anchor_position_idx": artifact.get("position_idx"),
                    "evidence": [{"excerpt": artifact.get("normalized_text") or ""}],
                    "metadata": {"task": task, "note": meta.get("capture_status", "capture_issue"), "source_stage": "visual"},
                }
            return self._fail_or_warn(task, criterion, note="capture_summary_missing")

        if task == "datalens_capture_artifacts_present":
            capture_images = [a for a in artifacts if a["artifact_type"] == "datalens_capture_image"]
            if capture_images:
                anchor = capture_images[0]
                return {
                    "status": "pass",
                    "confidence": 0.9,
                    "anchor_position_idx": anchor.get("position_idx"),
                    "evidence": [{"excerpt": anchor.get("normalized_text") or "", "count": len(capture_images)}],
                    "metadata": {"task": task, "capture_image_count": len(capture_images), "source_stage": "visual"},
                }
            return {
                "status": "warn" if criterion["severity"] != "required" else "fail",
                "confidence": 0.55,
                "anchor_position_idx": None,
                "evidence": [],
                "metadata": {"task": task, "note": "capture_images_missing", "source_stage": "visual"},
            }

        if task == "datalens_regions_inferred":
            regions = [a for a in artifacts if a["artifact_type"] == "datalens_region"]
            strong_regions = [a for a in regions if (a.get("metadata_json") or {}).get("region_kind") in {"filter", "metric", "chart"}]
            if strong_regions:
                anchor = strong_regions[0]
                return {
                    "status": "pass",
                    "confidence": 0.79,
                    "anchor_position_idx": anchor.get("position_idx"),
                    "evidence": [{"excerpt": (anchor.get("normalized_text") or "")[:200], "region_kind": (anchor.get("metadata_json") or {}).get("region_kind")}],
                    "metadata": {
                        "task": task,
                        "region_count": len(regions),
                        "strong_region_count": len(strong_regions),
                        "source_stage": "visual",
                    },
                }
            return self._fail_or_warn(task, criterion, note="no_datalens_regions")

        if task == "datalens_image_regions_extracted":
            return self._count_artifacts(task, artifacts, criterion, "datalens_image_region", note="datalens_image_regions_present")

        if task == "datalens_capture_overlays_saved":
            return self._count_artifacts(task, artifacts, criterion, "datalens_capture_overlay", note="datalens_capture_overlays_present")

        if task == "has_metric_regions":
            return self._find_signal(task, artifacts, criterion, signal="metric")

        if task == "has_filter_regions":
            return self._find_signal(task, artifacts, criterion, signal="filter")

        if task == "has_chart_regions":
            return self._chart_or_table(task, artifacts, criterion, kinds={"chart"})

        if task == "has_table_regions":
            return self._chart_or_table(task, artifacts, criterion, kinds={"table"})

        if task == "low_text_extraction_quality":
            short = 0
            total = 0
            for artifact in artifacts:
                if artifact["artifact_type"] not in {"pdf_page", "datalens_text_fragment"}:
                    continue
                total += 1
                text = (artifact.get("normalized_text") or "").strip()
                if len(text) < 12:
                    short += 1
            if total == 0:
                return self._fail_or_warn(task, criterion, note="no_text_artifacts")
            ratio = short / max(total, 1)
            if ratio > 0.5:
                return {
                    "status": "warn",
                    "confidence": 0.62,
                    "anchor_position_idx": None,
                    "evidence": [{"short_text_pages": short, "total": total}],
                    "metadata": {"task": task, "note": "many_low_text_pages", "source_stage": "visual"},
                }
            return {
                "status": "pass",
                "confidence": 0.75,
                "anchor_position_idx": None,
                "evidence": [{"short_text_pages": short, "total": total}],
                "metadata": {"task": task, "source_stage": "visual"},
            }

        if task == "low_region_confidence":
            lows = []
            for artifact in artifacts:
                if artifact["artifact_type"] not in {"pdf_image_region", "datalens_image_region"}:
                    continue
                meta = artifact.get("metadata_json") or {}
                conf = meta.get("region_confidence")
                if conf is not None and float(conf) < 0.45:
                    lows.append(artifact.get("position_idx"))
            if len(lows) >= 3:
                return {
                    "status": "warn",
                    "confidence": 0.6,
                    "anchor_position_idx": None,
                    "evidence": [{"low_confidence_regions": lows[:10]}],
                    "metadata": {"task": task, "source_stage": "visual"},
                }
            return {
                "status": "pass",
                "confidence": 0.72,
                "anchor_position_idx": None,
                "evidence": [],
                "metadata": {"task": task, "source_stage": "visual"},
            }

        if task == "overlay_generated":
            overlays = [a for a in artifacts if a["artifact_type"] in {"pdf_page_overlay", "datalens_capture_overlay"}]
            if overlays:
                anchor = overlays[0]
                return {
                    "status": "pass",
                    "confidence": 0.85,
                    "anchor_position_idx": anchor.get("position_idx"),
                    "evidence": [{"count": len(overlays)}],
                    "metadata": {"task": task, "source_stage": "visual"},
                }
            return self._fail_or_warn(task, criterion, note="no_overlay_artifacts")

        return {
            "status": "unknown",
            "confidence": 0.2,
            "anchor_position_idx": None,
            "evidence": [],
            "metadata": {"task": task, "note": "not implemented", "source_stage": "visual"},
        }

    def _find_signal(self, task: str, artifacts: list[dict], criterion: dict, signal: str) -> dict:
        for artifact in artifacts:
            meta = artifact.get("metadata_json") or {}
            tags = meta.get("tags") or []
            if signal in tags or meta.get("region_kind") == signal:
                return {
                    "status": "pass",
                    "confidence": 0.78,
                    "anchor_position_idx": artifact.get("position_idx"),
                    "evidence": [{"excerpt": (artifact.get("normalized_text") or "")[:200], "tags": tags, "region_kind": meta.get("region_kind")}],
                    "metadata": {"task": task, "signal": signal, "source_stage": "visual"},
                }
        return self._fail_or_warn(task, criterion, note=f"signal_{signal}_not_found")

    def _count_artifacts(self, task: str, artifacts: list[dict], criterion: dict, artifact_type: str, note: str) -> dict:
        items = [a for a in artifacts if a["artifact_type"] == artifact_type]
        if items:
            anchor = items[0]
            return {
                "status": "pass",
                "confidence": 0.87,
                "anchor_position_idx": anchor.get("position_idx"),
                "evidence": [{"excerpt": (anchor.get("normalized_text") or "")[:200], "count": len(items)}],
                "metadata": {"task": task, "count": len(items), "note": note, "source_stage": "visual"},
            }
        return self._fail_or_warn(task, criterion, note=f"{artifact_type}_missing")

    def _chart_or_table(self, task: str, artifacts: list[dict], criterion: dict, kinds: set[str]) -> dict:
        for artifact in artifacts:
            meta = artifact.get("metadata_json") or {}
            rk = meta.get("region_kind")
            if rk in kinds:
                return {
                    "status": "pass",
                    "confidence": 0.77,
                    "anchor_position_idx": artifact.get("position_idx"),
                    "evidence": [{"excerpt": (artifact.get("normalized_text") or "")[:200], "region_kind": rk}],
                    "metadata": {"task": task, "source_stage": "visual"},
                }
        return self._fail_or_warn(task, criterion, note=f"no_{'_or_'.join(sorted(kinds))}_regions")

    def _pass(self, artifact: dict, task: str, note: str) -> dict:
        return {
            "status": "pass",
            "confidence": 0.82,
            "anchor_position_idx": artifact.get("position_idx"),
            "evidence": [{"excerpt": (artifact.get("normalized_text") or "")[:200]}],
            "metadata": {"task": task, "note": note, "source_stage": "visual"},
        }

    def _fail_or_warn(self, task: str, criterion: dict, note: str) -> dict:
        return {
            "status": "fail" if criterion["severity"] == "required" else "warn",
            "confidence": 0.6,
            "anchor_position_idx": None,
            "evidence": [],
            "metadata": {"task": task, "note": note, "source_stage": "visual"},
        }
