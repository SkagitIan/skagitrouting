from ..models import AuditEvent, WorkspaceRevision


def record_event(actor, action, obj, metadata=None):
    AuditEvent.objects.create(
        actor=actor,
        action=action,
        object_type=obj.__class__.__name__,
        object_id=str(obj.pk),
        metadata=metadata or {},
    )


def record_workspace_revision(workspace, actor, action):
    WorkspaceRevision.objects.create(
        workspace=workspace,
        revision_number=workspace.revision,
        actor=actor,
        action=action,
        snapshot=workspace.state or {},
    )
