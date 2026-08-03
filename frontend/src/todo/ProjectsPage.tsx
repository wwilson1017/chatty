import { useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import type { TodoProject, TodoProjectStatus } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { IconPlus } from '../shared/icons';
import { FONT_MONO, INK, INK_DIM, INK_SOFT, LINE } from '../shared/styles';
import { pageHeading, filterBar, filterTab, btnPrimary, btnSmall, cardStyle, listContainer } from './styles';
import { PROJECT_STATUS_META, PROJECT_STATUS_ORDER } from './constants';
import { ProjectForm } from './components/ProjectForm';
import { ListFilterBar } from './components/ListFilterBar';
import { updateProjectStatus } from './projectActions';
import type { TodoOutletContext } from './TodoLayout';

export function ProjectsPage() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { projects, refreshMeta } = useOutletContext<TodoOutletContext>();
  const [filter, setFilter] = useState<TodoProjectStatus>('active');
  const [showCreate, setShowCreate] = useState(false);
  const [search, setSearch] = useState('');

  const q = search.trim().toLowerCase();
  const visible = projects.filter(p =>
    p.status === filter
    && (!q || p.name.toLowerCase().includes(q) || p.notes.toLowerCase().includes(q)),
  );

  async function setStatus(project: TodoProject, status: TodoProjectStatus) {
    if (await updateProjectStatus(project.id, status)) refreshMeta();
  }

  const statusBadge = (status: TodoProjectStatus) => {
    const meta = PROJECT_STATUS_META[status];
    return (
      <span style={{
        fontSize: 11, padding: '3px 10px', borderRadius: 4,
        fontFamily: FONT_MONO, letterSpacing: '0.08em', fontWeight: 500,
        background: meta.bg, color: meta.color, whiteSpace: 'nowrap',
      }}>{meta.label}</span>
    );
  };

  return (
    <div style={{ padding: isMobile ? '20px 16px' : '32px 44px', maxWidth: 900 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: isMobile ? 16 : 24 }}>
        <h1 style={pageHeading(isMobile)}>Projects</h1>
        <button onClick={() => setShowCreate(true)} style={{ ...btnPrimary, padding: '7px 14px', fontSize: 13 }}>
          <IconPlus size={13} strokeWidth={2.25} /> {isMobile ? 'New' : 'New Project'}
        </button>
      </div>

      <div style={filterBar(isMobile)}>
        {PROJECT_STATUS_ORDER.map(s => (
          <button
            key={s}
            onClick={() => setFilter(s)}
            style={filterTab(isMobile, filter === s, PROJECT_STATUS_META[s].color)}
          >{PROJECT_STATUS_META[s].label}</button>
        ))}
      </div>

      <ListFilterBar
        search={search} onSearch={setSearch}
        isMobile={isMobile} placeholder="Search projects..."
      />

      {visible.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>
            {q ? 'No projects match your search.'
              : `No ${PROJECT_STATUS_META[filter].label.toLowerCase()} projects.`}
          </p>
        </div>
      ) : (
        <div style={listContainer(isMobile)}>
          {visible.map(project => (
            <div
              key={project.id}
              onClick={() => navigate(`/todos/projects/${project.id}`)}
              style={isMobile
                ? { padding: '14px', cursor: 'pointer', ...cardStyle }
                : {
                    display: 'flex', alignItems: 'center', gap: 12,
                    padding: '14px 16px', cursor: 'pointer',
                    borderBottom: `1px solid ${LINE}`,
                  }
              }
              onMouseEnter={e => { (e.currentTarget as HTMLElement).style.background = 'rgba(200,209,217,0.04)'; }}
              onMouseLeave={e => { (e.currentTarget as HTMLElement).style.background = isMobile ? '' : 'transparent'; }}
            >
              <div style={{ flex: 1, minWidth: 0, display: isMobile ? 'block' : undefined }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: project.notes ? 3 : 0 }}>
                  <span style={{ fontSize: 16, color: INK }}>{project.name}</span>
                  {statusBadge(project.status)}
                </div>
                {project.notes && (
                  <p style={{
                    fontSize: 13, color: INK_SOFT, margin: 0,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{project.notes}</p>
                )}
              </div>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0,
                marginTop: isMobile ? 8 : 0,
              }}>
                <span style={{ fontSize: 13, color: INK_SOFT }}>{project.open_count} open</span>
                <button
                  onClick={e => {
                    e.stopPropagation();
                    setStatus(project, project.status === 'completed' || project.status === 'dropped' ? 'active' : 'completed');
                  }}
                  title={project.status === 'completed' || project.status === 'dropped'
                    ? 'Reopen this project'
                    : 'Mark this project completed'}
                  style={{ ...btnSmall, background: 'transparent', border: '1px solid rgba(230,235,242,0.14)', color: INK_SOFT }}
                >
                  {project.status === 'completed' || project.status === 'dropped' ? 'Reactivate' : '✓ Complete'}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {showCreate && (
        <ProjectForm
          onClose={() => setShowCreate(false)}
          onSaved={() => { setShowCreate(false); refreshMeta(); }}
        />
      )}
    </div>
  );
}
