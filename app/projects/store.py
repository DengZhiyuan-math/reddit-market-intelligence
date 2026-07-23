"""Local JSON registry store for Phase 2 project persistence."""

from pathlib import Path

from app.projects.models import ProjectRegistry, ResearchProject


class ProjectRegistryStore:
    """Persist projects locally before Phase 3 introduces database storage."""

    def __init__(self, registry_path: Path) -> None:
        self.registry_path = registry_path

    def load(self) -> ProjectRegistry:
        if not self.registry_path.exists():
            return ProjectRegistry()
        return ProjectRegistry.model_validate_json(self.registry_path.read_text())

    def save(self, registry: ProjectRegistry) -> None:
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self.registry_path.write_text(registry.model_dump_json(indent=2) + "\n")

    def next_project_id(self) -> int:
        registry = self.load()
        project_id = registry.next_project_id
        registry.next_project_id += 1
        self.save(registry)
        return project_id

    def add_project(self, project: ResearchProject) -> None:
        registry = self.load()
        registry.projects.append(project)
        registry.next_project_id = max(registry.next_project_id, project.project_id + 1)
        self.save(registry)

    def update_project(self, project: ResearchProject) -> None:
        registry = self.load()
        for index, existing in enumerate(registry.projects):
            if existing.project_id == project.project_id:
                registry.projects[index] = project
                self.save(registry)
                return
        registry.projects.append(project)
        registry.next_project_id = max(registry.next_project_id, project.project_id + 1)
        self.save(registry)

    def list_projects(self) -> list[ResearchProject]:
        return self.load().projects

    def get_project(self, project_id: int) -> ResearchProject | None:
        for project in self.load().projects:
            if project.project_id == project_id:
                return project
        return None
