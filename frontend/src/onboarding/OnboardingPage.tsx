import { useNavigate } from 'react-router-dom';
import { OnboardingWizard } from './OnboardingWizard';

export function OnboardingPage() {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen bg-gray-950 flex items-center justify-center p-6">
      <div className="w-full max-w-2xl">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white">Welcome to Chatty</h1>
          <p className="text-gray-400 mt-2">Let's get you set up in a few quick steps</p>
        </div>
        <OnboardingWizard onComplete={() => navigate('/', { replace: true })} />
      </div>
    </div>
  );
}
