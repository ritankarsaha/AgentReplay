import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { CopyButton } from "@/components/copy-button";
import { CreateProjectForm, RotateKeyForm } from "@/components/project-forms";
import { RelativeTime } from "@/components/relative-time";
import { getViewerContext } from "@/lib/viewer";

export default async function ProjectsPage() {
  const { projects, active } = await getViewerContext();
  const endpoint = process.env.NEXT_PUBLIC_AGENTREPLAY_ENDPOINT;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-6 py-10">
      <div>
        <h1 className="text-lg font-semibold">
          {projects.length === 0 ? "Create your first project" : "Projects"}
        </h1>
        <p className="text-sm text-muted-foreground">
          {projects.length === 0
            ? "A project groups the runs from one agent and gets its own API key. Create one to start recording."
            : "Each project has its own API key and its own runs. Only you can see them."}
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{projects.length === 0 ? "Name your project" : "New project"}</CardTitle>
        </CardHeader>
        <CardContent>
          <CreateProjectForm firstProject={projects.length === 0} />
        </CardContent>
      </Card>

      {projects.map((project) => (
        <Card key={project.id}>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              {project.name}
              {project.id === active?.id && (
                <span className="rounded-sm bg-muted px-1.5 py-0.5 font-mono text-[0.65rem] font-normal text-muted-foreground">
                  active
                </span>
              )}
            </CardTitle>
            <p className="font-mono text-xs text-muted-foreground">
              created <RelativeTime iso={project.created_at} />
            </p>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 font-mono text-xs">
              <dt className="text-muted-foreground">project id</dt>
              <dd className="flex items-center gap-1.5">
                {project.id}
                <CopyButton value={project.id} label="Copy project id" />
              </dd>
              <dt className="text-muted-foreground">api key</dt>
              <dd>{project.api_key_prefix ?? "ar_"}… (shown once at creation)</dd>
              {endpoint && (
                <>
                  <dt className="text-muted-foreground">endpoint</dt>
                  <dd>{endpoint}</dd>
                </>
              )}
            </dl>
            <RotateKeyForm projectId={project.id} />
          </CardContent>
        </Card>
      ))}
    </main>
  );
}
