interface Step {
  id: string;
  title: string;
}

interface Props {
  steps: Step[];
  currentIndex: number;
}

export function StepIndicator({ steps, currentIndex }: Props) {
  return (
    <div className="flex items-center justify-center gap-2 mb-8">
      {steps.map((step, i) => {
        const isCompleted = i < currentIndex;
        const isCurrent = i === currentIndex;

        return (
          <div key={step.id} className="flex items-center gap-2">
            {i > 0 && (
              <div className={`w-8 h-px ${isCompleted ? 'bg-indigo-500' : 'bg-gray-700'}`} />
            )}
            <div className="flex flex-col items-center gap-1.5">
              <div
                className={`w-8 h-8 rounded-full flex items-center justify-center text-xs font-semibold transition ${
                  isCompleted
                    ? 'bg-indigo-500 text-white'
                    : isCurrent
                      ? 'bg-indigo-500/20 text-indigo-400 ring-2 ring-indigo-500'
                      : 'bg-gray-800 text-gray-500'
                }`}
              >
                {isCompleted ? (
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                ) : (
                  i + 1
                )}
              </div>
              <span className={`text-xs whitespace-nowrap ${isCurrent ? 'text-gray-300' : 'text-gray-500'}`}>
                {step.title}
              </span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
