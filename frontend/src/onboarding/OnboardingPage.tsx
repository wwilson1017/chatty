import { useNavigate } from 'react-router-dom';
import { OnboardingWizard } from './OnboardingWizard';
import { IconWordmark } from '../shared/icons';
import { WarmHalo } from '../shared/WarmHalo';
import { useIsMobile } from '../shared/useIsMobile';

export function OnboardingPage() {
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  return (
    <div style={{
      minHeight: '100vh', background: '#0A0C0F', color: '#EDF0F4',
      fontFamily: "'Inter Tight', 'Inter', system-ui, sans-serif",
      display: 'flex', flexDirection: 'column', overflow: 'hidden',
      position: 'relative',
    }}>
      <WarmHalo opacity={0.55} />

      {/* Header */}
      <div style={{
        height: isMobile ? 80 : 72, padding: '0 32px',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        borderBottom: '1px solid rgba(230,235,242,0.07)',
        position: 'relative', zIndex: 2,
      }}>
        <div style={{ color: 'var(--color-ch-accent, #C8D1D9)' }}>
          <IconWordmark height={isMobile ? 64 : 44} color="currentColor" />
        </div>
      </div>

      {/* Content */}
      <div style={{
        flex: 1, display: 'flex', alignItems: isMobile ? 'flex-start' : 'center', justifyContent: 'center',
        padding: isMobile ? '24px 20px' : 40, position: 'relative', zIndex: 2,
        overflowY: 'auto',
      }}>
        <div style={{ maxWidth: 680, width: '100%' }}>
          <OnboardingWizard onComplete={() => navigate('/', { replace: true })} />
        </div>
      </div>
    </div>
  );
}
