"""CSV upload screen (Head of Collections / COO)."""
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Role, UploadBatch, User
from app.security import require_roles
from app.services.upload import (
    OPTIONAL_COLUMNS, REQUIRED_COLUMNS, UploadError, first_errors, import_accounts,
)
from app.web import flash, render

router = APIRouter()
uploader = require_roles(Role.HEAD, Role.COO)


@router.get("/upload")
def upload_page(request: Request, batch: int | None = None, user: User = Depends(uploader),
                db: Session = Depends(get_db)):
    batches = list(db.scalars(select(UploadBatch).order_by(UploadBatch.id.desc()).limit(10)))
    current = db.get(UploadBatch, batch) if batch else None
    return render(request, "upload.html", user, batches=batches, current=current,
                  errors=first_errors(current) if current else [],
                  required=REQUIRED_COLUMNS, optional=OPTIONAL_COLUMNS)


@router.post("/upload")
def upload_csv(request: Request, file: UploadFile = File(...), user: User = Depends(uploader),
               db: Session = Depends(get_db)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        flash(request, "Please choose a .csv file.", "error")
        return RedirectResponse("/upload", status_code=303)
    try:
        batch = import_accounts(db, file.file, file.filename, user)
    except UploadError as exc:
        db.rollback()
        flash(request, str(exc), "error")
        return RedirectResponse("/upload", status_code=303)
    except UnicodeDecodeError:
        db.rollback()
        flash(request, "The file is not UTF-8 text. Save it as 'CSV UTF-8' and try again.", "error")
        return RedirectResponse("/upload", status_code=303)
    flash(request, f"Imported {batch.inserted:,} accounts from {batch.filename} "
                   f"in {batch.duration_ms / 1000:.1f}s.")
    return RedirectResponse(f"/upload?batch={batch.id}", status_code=303)


@router.get("/upload/{batch_id}/errors.csv")
def upload_errors(batch_id: int, user: User = Depends(uploader), db: Session = Depends(get_db)):
    batch = db.get(UploadBatch, batch_id)
    if batch is None or not batch.errors_csv:
        raise HTTPException(status_code=404)
    return Response(batch.errors_csv, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="upload-{batch_id}-errors.csv"'})
