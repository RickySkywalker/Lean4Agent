import Editor from '@monaco-editor/react';
import { AlertCircle, CheckCircle2, ChevronDown, ChevronUp } from 'lucide-react';
import { useState } from 'react';

interface YamlEditorProps {
  value: string;
  onChange: (value: string) => void;
  error?: string | null;
}

export default function YamlEditor({ value, onChange, error }: YamlEditorProps) {
  const [isErrorExpanded, setIsErrorExpanded] = useState(false);

  // Format error message for better display
  const formatError = (errorMsg: string) => {
    // Split by common separators in yaml error messages
    return errorMsg.split(/(?=\d+\s*\|)/g).filter(Boolean);
  };

  const errorLines = error ? formatError(error) : [];
  const hasMultipleLines = errorLines.length > 1 || (error && error.length > 80);

  // Prevent keyboard events from bubbling to React Flow
  // This allows typing spaces, backspace, etc. in the editor
  const handleKeyDown = (e: React.KeyboardEvent) => {
    e.stopPropagation();
  };

  return (
    <div className="h-full flex flex-col" onKeyDown={handleKeyDown}>
      <div className="px-4 py-3 border-b border-gray-200 bg-white">
        <span className="font-semibold text-gray-800 text-sm">YAML Editor</span>
        <p className="text-xs text-gray-500 mt-1">
          Edit the YAML directly. Changes will sync to the canvas.
        </p>
      </div>
      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          defaultLanguage="yaml"
          value={value}
          onChange={(val) => onChange(val || '')}
          theme="vs-light"
          options={{
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: 'on',
            wordWrap: 'on',
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            insertSpaces: true,
          }}
        />
      </div>
      {/* Syntax status bar */}
      {error ? (
        <div className="border-t border-red-200 bg-red-50 text-red-700">
          {/* Clickable header */}
          <div 
            className={`px-3 py-2 flex items-center gap-2 text-xs ${hasMultipleLines ? 'cursor-pointer hover:bg-red-100' : ''}`}
            onClick={() => hasMultipleLines && setIsErrorExpanded(!isErrorExpanded)}
          >
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span className="font-semibold">Syntax Error</span>
            {hasMultipleLines && (
              <>
                <span className="text-red-500">({isErrorExpanded ? 'click to collapse' : 'click to expand'})</span>
                {isErrorExpanded ? (
                  <ChevronUp className="w-4 h-4 ml-auto flex-shrink-0" />
                ) : (
                  <ChevronDown className="w-4 h-4 ml-auto flex-shrink-0" />
                )}
              </>
            )}
          </div>
          {/* Error details */}
          <div className={`px-3 pb-2 text-xs ${isErrorExpanded ? '' : 'max-h-6 overflow-hidden'}`}>
            <pre className="whitespace-pre-wrap font-mono text-red-600 leading-relaxed">
              {error}
            </pre>
            {isErrorExpanded && (
              <p className="mt-2 text-red-500 text-xs italic border-t border-red-200 pt-2">
                💡 Tip: The actual error may be on a line before the indicated position. Check nearby syntax (missing colons, unmatched quotes, indentation issues, etc.)
              </p>
            )}
          </div>
        </div>
      ) : (
        <div className="px-3 py-2 border-t border-green-200 bg-green-50 text-green-700 flex items-center gap-2 text-xs">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
          <span>YAML syntax valid</span>
        </div>
      )}
    </div>
  );
}

