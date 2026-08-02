import { useState } from 'react';
import { useNavigate, useOutletContext } from 'react-router-dom';
import type { TodoProjectStatus } from '../core/types';
import { useIsMobile } from '../shared/useIsMobile';
import { IconPlus } from '../shared/icons';
import { FONT_MONO, INK, INK_DIM, INK_SOFT, LINE } from '../shared/styles';
import { pageHeading, filterBar, filterTab, btnPrimary, cardStyle, listContainer } from './styles';
import { PROJECT_STATUS_META, PROJECT_STATUS_ORDER } from './constants';
import { ProjectForm } from './components/ProjectForm';
import type { TodoOutletContext } from './TodoLayout';

export function ProjectsPage() {
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { projects, refreshMeta } = useOutletContext<TodoOutletContext>();
  const [filter, setFilter] = useState<TodoProjectStatus>('active');
  const [showCreate, setShowCreate] = useState(false);

  const visible = projects.filter(p => p.status === filter);

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

      {visible.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '64px 0' }}>
          <p style={{ color: INK_DIM, fontSize: 14 }}>
            No {PROJECT_STATUS_META[filter].label.toLowerCase()} projects.
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
              <span style={{ fontSize: 13, color: INK_SOFT, flexShrink: 0, marginTop: isMobile ? 6 : 0, display: isMobile ? 'block' : undefined }}>
                {project.open_count} open
              </span>
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
