"""Independent, actionable tasks and their supporting project resources."""
from datetime import timedelta

RESOURCES = {
    "finance_overview": ("AI for Financial Analysis Assistant — Project Overview", "financial-analysis-overview.docx"),
    "finance_progress": ("AI for Financial Analysis Assistant — Progress and Findings", "financial-analysis-progress.pptx"),
    "finance_next_steps": ("AI for Financial Analysis Assistant — Next Steps", "financial-analysis-next-steps.docx"),
    "notes_overview": ("Local AI Meeting Notes Assistant — Design Outline", "local-meeting-notes-overview.docx"),
}

TASKS = [
    {
        "key": "leah_ramp_up",
        "title": "Draft Leah Moreno’s ramp-up email for the AI for Financial Analysis assistant",
        "notes": "Leah is taking over the AI for Financial Analysis assistant. Put together a draft with the project resources, a quick explanation of each, and where she should start.",
        "resources": ("finance_overview", "finance_progress", "finance_next_steps"),
    },
    {
        "key": "gtc_invitation",
        "title": "Draft my GTC 2027 availability reply to Tessa",
        "notes": "Tessa needs my availability. A yes or no is enough for now; demo details can wait. Draft a short reply once I confirm.",
        "resources": (),
    },
    {
        "key": "notes_design",
        "title": "Define the Local AI Meeting Notes Assistant’s rough design in the project doc",
        "notes": "Evan is waiting on my proposed design. Work through the user experience, choose what belongs in the first prototype, and explain the approach and tradeoffs in the doc.",
        "resources": ("notes_overview",),
    },
]

LEGACY_SUBJECTS = {
    "Publish a customer demo FAQ", "Share the pilot-program lessons learned",
    "Finalize the developer workshop budget",
    "Prototype ETA for the Local AI Meeting Notes Assistant",
}


def date_label(day):
    return f"{day.strftime('%A, %B')} {day.day}, {day.year}"


def email_specs(resources, today):
    """Incoming mail only. No user decision or outgoing response is fabricated."""
    url = lambda key: resources[key]["url"]
    return [
        ("Leah Moreno <leah.moreno@example.com>", "Getting started on the AI for Financial Analysis assistant",
         f"Hi,\n\nI’m taking over the AI for Financial Analysis assistant and would love a quick steer on where to start. Could you send me a short rundown of the project resources today, including what each one covers and what I should read first?\n\nI found these in Drive, but a bit of context would help me get up to speed before I sit down with Engineering.\n\nProject Overview: {url('finance_overview')}\nProgress and Findings: {url('finance_progress')}\nNext Steps: {url('finance_next_steps')}\n\nThanks,\nLeah"),
        ("Tessa Ellis <tessa.ellis@example.com>", "Following up: demo presenter for GTC 2027",
         f"Hi,\n\nCircling back on our conversation on {date_label(today - timedelta(days=7))} about having you present a demo at GTC 2027. You mentioned needing a week to decide whether you’d be available.\n\nWould you be able to let me know today? A yes or no is enough for now so I can update the presenter list. We can work through the demo details afterward if you’re able to join.\n\nThanks,\nTessa\nGTC demo program coordinator"),
        ("Evan Mercer <evan.mercer@example.com>", "Following up on the Local AI Meeting Notes Assistant design",
         f"Hi,\n\nHave you had a chance to update the Local AI Meeting Notes Assistant doc with your proposed design? Your take on the user experience and what we should include in the first prototype would help us plan the engineering work.\n\nCould you add your outline today? It doesn’t need to be polished, just enough to explain the approach and the main tradeoffs.\n\nProject doc: {url('notes_overview')}\n\nThanks,\nEvan"),
    ]


def task_bodies(resources, evidence, today, marker):
    for task in TASKS:
        links = "\n".join(f"{RESOURCES[key][0]}: {resources[key]['url']}" for key in task["resources"])
        notes = f"{task['notes']}\n\nSource email: {evidence[task['key']]}"
        if links:
            notes += "\n\n" + links
        yield {
            "title": task["title"], "notes": notes + f"\n\n[{marker}]",
            "status": "needsAction", "due": today.isoformat() + "T00:00:00Z",
        }


def ensure_resources(seed, svc, state, *, checkpoint=lambda: None, restore=False):
    """Import native files, retaining their IDs and links on subsequent resets."""
    from googleapiclient.http import MediaFileUpload
    resources = state.setdefault("task_resources", {})
    restores = []
    for key, (title, filename) in RESOURCES.items():
        slides = filename.endswith(".pptx")
        native = "application/vnd.google-apps." + ("presentation" if slides else "document")
        office = "application/vnd.openxmlformats-officedocument." + ("presentationml.presentation" if slides else "wordprocessingml.document")
        if key not in resources:
            resources[key] = seed.upload_template(svc["drive"], state["folder"]["id"], filename, title, native)
            checkpoint()
        elif restore:
            restores.append((resources[key]["id"], title, filename, native, office))

    def restore_one(drive, file_id, title, filename, native, office):
        drive.files().update(fileId=file_id, body={"mimeType": native, "name": title},
            media_body=MediaFileUpload(str(seed.ROOT / "demo" / "templates" / filename), mimetype=office, resumable=False), fields="id").execute()

    make_drive = getattr(seed, "drive_service", None)
    if len(restores) > 1 and make_drive is not None:
        # Each Office re-import is a slow, independent upload; run them concurrently on separate clients.
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=len(restores)) as pool:
            futures = [pool.submit(lambda item: restore_one(make_drive(), *item), item) for item in restores]
            for future in futures:
                future.result()
    else:
        for item in restores:
            restore_one(svc["drive"], *item)


def tracked_mail_metadata(gmail, items):
    """A previously seeded message may have been deleted by the user."""
    results = [None] * len(items)
    failures = []
    def receive(request_id, response, error):
        if error is not None:
            if getattr(getattr(error, "resp", None), "status", None) != 404:
                failures.append(error)
        else:
            results[int(request_id)] = response
    for start in range(0, len(items), 50):
        batch = gmail.new_batch_http_request()
        for i in range(start, min(start + 50, len(items))):
            request = gmail.users().messages().get(userId="me", id=items[i]["id"], format="metadata", metadataHeaders=["Subject", "Message-ID"])
            batch.add(request, callback=receive, request_id=str(i))
        batch.execute()
        if failures:
            raise failures[0]
    return results


def refresh(seed, state):
    """Replace only seeded tasks and their three supporting emails. No broad reset."""
    import json
    import uuid
    svc = seed.services(tasks_required=True)
    folder = svc["drive"].files().get(fileId=state["folder"]["id"], fields="id,trashed").execute()
    if folder.get("trashed"):
        raise RuntimeError("This state points to a trashed demo folder. Use the active demo profile.")
    def save():
        path = seed.state_path()
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
        temporary.replace(path)
    ensure_resources(seed, svc, state, checkpoint=save)
    now = seed.local_now()
    specs = email_specs(state["task_resources"], now.date())
    allowed_subjects = LEGACY_SUBJECTS | {item[1] for item in specs}
    metadata = tracked_mail_metadata(svc["gmail"], state["emails"])
    replace_ids = []
    missing_ids = []
    for item, message in zip(state["emails"], metadata):
        if message is None:
            missing_ids.append(item["id"])
            continue
        headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
        if headers.get("subject") in allowed_subjects and headers.get("message-id", "").startswith(f"<{seed.MARKER}-"):
            replace_ids.append(item["id"])
    if replace_ids:
        svc["gmail"].users().messages().batchDelete(userId="me", body={"ids": replace_ids}).execute()
    if replace_ids or missing_ids:
        state["emails"] = [item for item in state["emails"] if item["id"] not in replace_ids + missing_ids]
        save()
    account = svc["gmail"].users().getProfile(userId="me").execute()["emailAddress"]
    run_id = uuid.uuid4().hex
    evidence = {}
    times = seed.seeded_inbox_times(now)[-len(TASKS):]
    for i, ((sender, subject, body), when, task) in enumerate(zip(specs, times, TASKS), 1):
        result = seed.mail_import_request(svc["gmail"], account, sender, subject, body, i, when, run_id, important=False).execute()
        item = {"id": result["id"], "thread_id": result.get("threadId", result["id"]), "task_key": task["key"]}
        item["url"] = f"https://mail.google.com/mail/u/#all/{item['thread_id']}"
        state["emails"].append(item)
        evidence[task["key"]] = item["url"]
        save()
    seed.clear_seeded_tasks(svc["tasks"], state)
    save()
    seed.create_tasks(svc["tasks"], state, evidence)
    state["task_scenario_date"] = now.date().isoformat()
    save()
    return state
