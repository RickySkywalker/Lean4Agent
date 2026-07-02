import { useState, useRef, useEffect } from 'react';
import {
  Download,
  Upload,
  LayoutGrid,
  Code,
  Eye,
  Trash2,
  Image,
  ChevronDown,
  FileImage,
  FileType,
  FileText,
  Undo2,
  Redo2,
  Play,
  LayoutDashboard,
  FolderOpen,
  Package,
  Github,
} from 'lucide-react';
import { ImageFormat, getSupportedFormats } from '../utils/image';

export type RunOptions = {
  dashboard: boolean;
  resume: boolean;
  model: string;
  maxTokensPerStep: string;
  maxToolCallsPerStep: string;
  planRevisionMaxSteps: string;
  mcpUrl: string;
  outputDir: string;
  checkpointPath: string;
  tracePath: string;
  replayTrace: string;
  extraArgs: string;
};

interface ToolbarProps {
  onAutoLayout: () => void;
  layoutDirection: 'TB' | 'LR';
  onLayoutDirectionChange: (direction: 'TB' | 'LR') => void;
  layoutCompact: boolean;
  onLayoutCompactChange: (compact: boolean) => void;
  onExport: () => void;
  onExportFolder?: () => void;
  onExportImage: (format: ImageFormat, scale: number) => void;
  onImport: () => void;
  onImportSubmodules?: () => void;
  onImportFolder?: () => void;
  onClear: () => void;
  showYamlEditor: boolean;
  onToggleYamlEditor: () => void;
  onUndo: () => void;
  onRedo: () => void;
  canUndo: boolean;
  canRedo: boolean;
  onRun: () => void;
  runDisabled: boolean;
  runLabel?: string;
  runOptions: RunOptions;
  onRunOptionsChange: (patch: Partial<RunOptions>) => void;
  dashboardAvailable: boolean;
  onOpenDashboard: () => void;
  outputAvailable?: boolean;
  onOpenOutput?: () => void;
}

const FORMAT_ICONS: Record<ImageFormat, React.ElementType> = {
  png: FileImage,
  svg: FileType,
  pdf: FileText,
};

const SCALE_OPTIONS = [
  { value: 1, label: '1x', description: 'Standard' },
  { value: 2, label: '2x', description: 'High-res' },
  { value: 3, label: '3x', description: 'Ultra' },
  { value: 4, label: '4x', description: 'Maximum' },
];

// Detect if running on macOS
const isMac = typeof navigator !== 'undefined' && navigator.platform.toUpperCase().indexOf('MAC') >= 0;

export default function Toolbar({
  onAutoLayout,
  layoutDirection,
  onLayoutDirectionChange,
  layoutCompact,
  onLayoutCompactChange,
  onExport,
  onExportFolder,
  onExportImage,
  onImport,
  onImportSubmodules,
  onImportFolder,
  onClear,
  showYamlEditor,
  onToggleYamlEditor,
  onUndo,
  onRedo,
  canUndo,
  canRedo,
  onRun,
  runDisabled,
  runLabel = 'Run',
  runOptions,
  onRunOptionsChange,
  dashboardAvailable,
  onOpenDashboard,
  outputAvailable = false,
  onOpenOutput,
}: ToolbarProps) {
  const [showExportMenu, setShowExportMenu] = useState(false);
  const [showRunMenu, setShowRunMenu] = useState(false);
  const [showImportMenu, setShowImportMenu] = useState(false);
  const [showLayoutMenu, setShowLayoutMenu] = useState(false);
  const [selectedScale, setSelectedScale] = useState(2);
  const menuRef = useRef<HTMLDivElement>(null);
  const runMenuRef = useRef<HTMLDivElement>(null);
  const importMenuRef = useRef<HTMLDivElement>(null);
  const layoutMenuRef = useRef<HTMLDivElement>(null);

  // Close menu when clicking outside
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      const target = event.target as Node;
      if (menuRef.current && !menuRef.current.contains(target)) {
        setShowExportMenu(false);
      }
      if (runMenuRef.current && !runMenuRef.current.contains(target)) {
        setShowRunMenu(false);
      }
      if (importMenuRef.current && !importMenuRef.current.contains(target)) {
        setShowImportMenu(false);
      }
      if (layoutMenuRef.current && !layoutMenuRef.current.contains(target)) {
        setShowLayoutMenu(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const formats = getSupportedFormats();

  const handleExportFormat = (format: ImageFormat) => {
    onExportImage(format, selectedScale);
    setShowExportMenu(false);
  };

  return (
    <div className="relative z-30 h-9 border-b border-slate-200 bg-gradient-to-r from-slate-50 via-white to-slate-50/80 flex items-center px-3 gap-1.5 backdrop-blur">
      <div className="flex items-center gap-1.5">
        <span className="text-sm font-semibold text-slate-800 tracking-tight">YAML Flow Editor</span>
        <button
          onClick={onOpenDashboard}
          disabled={!dashboardAvailable}
          className={`px-1.5 py-0.5 rounded flex items-center gap-1 text-xs border ${
            dashboardAvailable
              ? 'border-gray-200 hover:bg-gray-100 text-gray-700'
              : 'border-gray-100 text-gray-300 cursor-not-allowed'
          }`}
          title={dashboardAvailable ? 'Open Dashboard' : 'Dashboard not available (enable Start Dashboard and run)'}
        >
          <LayoutDashboard size={12} />
          <span className="hidden sm:inline">Dashboard</span>
        </button>
        <button
          onClick={() => onOpenOutput?.()}
          disabled={!outputAvailable || !onOpenOutput}
          className={`px-1.5 py-0.5 rounded flex items-center gap-1 text-xs border ${
            outputAvailable && onOpenOutput
              ? 'border-gray-200 hover:bg-gray-100 text-gray-700'
              : 'border-gray-100 text-gray-300 cursor-not-allowed'
          }`}
          title={outputAvailable ? 'Open Output panel' : 'No output yet'}
        >
          <Eye size={12} />
          <span className="hidden sm:inline">Output</span>
        </button>
      </div>
      
      <div className="flex-1 min-w-2" />
      
      <div className="flex items-center gap-0.5">
        {/* Run split-button + options dropdown */}
        <div className="relative flex rounded-md bg-slate-900 text-white shadow-sm" ref={runMenuRef}>
          <button
            onClick={onRun}
            disabled={runDisabled}
            className={`px-2 py-1 flex items-center gap-1 text-xs rounded-l-md ${
              runDisabled
                ? 'opacity-40 cursor-not-allowed'
                : 'hover:bg-slate-800'
            }`}
            title="Run scripts/run_agent.sh from UI"
          >
            <Play size={14} />
            <span className="hidden sm:inline font-medium">{runLabel}</span>
          </button>
          <button
            onClick={() => setShowRunMenu(!showRunMenu)}
            className={`px-1.5 py-1 border-l border-slate-700 flex items-center rounded-r-md ${
              showRunMenu ? 'bg-slate-800' : 'hover:bg-slate-800/80'
            }`}
            title="Run options"
          >
            <ChevronDown size={12} className={`transition-transform ${showRunMenu ? 'rotate-180' : ''}`} />
          </button>

          {showRunMenu && (
            <div className="absolute left-0 top-full mt-1 w-[520px] bg-white rounded-lg shadow-lg border border-gray-200 z-50 flex flex-col max-h-[70vh]">
              <div className="px-3 py-2 border-b border-gray-100 flex-shrink-0">
                <div className="text-xs font-semibold text-gray-700">Run options</div>
                <div className="text-[11px] text-gray-500 mt-1">
                  Options apply to the next Run.
                </div>
              </div>

              <div className="px-3 py-2 space-y-3 overflow-y-auto overscroll-contain">
                <div className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide">Execution</div>
                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    className="accent-green-600"
                    checked={runOptions.dashboard}
                    onChange={(e) => onRunOptionsChange({ dashboard: e.target.checked })}
                  />
                  <span className="font-medium">Start Dashboard</span>
                  <span className="text-xs text-gray-500">(no auto-open)</span>
                </label>

                <label className="flex items-center gap-2 text-sm text-gray-700">
                  <input
                    type="checkbox"
                    className="accent-green-600"
                    checked={runOptions.resume}
                    onChange={(e) => onRunOptionsChange({ resume: e.target.checked })}
                  />
                  <span className="font-medium">Resume</span>
                  <span className="text-xs text-gray-500">(--resume)</span>
                </label>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <div className="text-xs font-medium text-gray-700 mb-1">Model</div>
                    <input
                      value={runOptions.model}
                      onChange={(e) => onRunOptionsChange({ model: e.target.value })}
                      placeholder="e.g. gpt-4.1-mini"
                      className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                    />
                    <div className="text-[11px] text-gray-500 mt-1">Maps to <code className="font-mono">--model=...</code></div>
                  </div>
                  <div>
                    <div className="text-xs font-medium text-gray-700 mb-1">MCP URL</div>
                    <input
                      value={runOptions.mcpUrl}
                      onChange={(e) => onRunOptionsChange({ mcpUrl: e.target.value })}
                      placeholder="e.g. http://localhost:7002/mcp"
                      className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                    />
                    <div className="text-[11px] text-gray-500 mt-1">Maps to <code className="font-mono">--mcp_url</code></div>
                  </div>
                </div>

                <div className="grid grid-cols-3 gap-2">
                  <div>
                    <div className="text-xs font-medium text-gray-700 mb-1">Max tokens/step</div>
                    <input
                      value={runOptions.maxTokensPerStep}
                      onChange={(e) => onRunOptionsChange({ maxTokensPerStep: e.target.value })}
                      placeholder="e.g. 20000"
                      inputMode="numeric"
                      className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                    />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-gray-700 mb-1">Max tool calls/step</div>
                    <input
                      value={runOptions.maxToolCallsPerStep}
                      onChange={(e) => onRunOptionsChange({ maxToolCallsPerStep: e.target.value })}
                      placeholder="e.g. 50"
                      inputMode="numeric"
                      className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                    />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-gray-700 mb-1">Plan revisions</div>
                    <input
                      value={runOptions.planRevisionMaxSteps}
                      onChange={(e) => onRunOptionsChange({ planRevisionMaxSteps: e.target.value })}
                      placeholder="e.g. 3"
                      inputMode="numeric"
                      className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                    />
                  </div>
                </div>

                <div className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide pt-1">Paths</div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <div className="text-xs font-medium text-gray-700 mb-1">Output dir</div>
                    <input
                      value={runOptions.outputDir}
                      onChange={(e) => onRunOptionsChange({ outputDir: e.target.value })}
                      placeholder="e.g. outputs/my_task"
                      className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                    />
                    <div className="text-[11px] text-gray-500 mt-1">Maps to <code className="font-mono">--output_dir</code></div>
                  </div>
                  <div>
                    <div className="text-xs font-medium text-gray-700 mb-1">Checkpoint path</div>
                    <input
                      value={runOptions.checkpointPath}
                      onChange={(e) => onRunOptionsChange({ checkpointPath: e.target.value })}
                      placeholder="e.g. outputs/my_task/checkpoint.json"
                      className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                    />
                    <div className="text-[11px] text-gray-500 mt-1">Maps to <code className="font-mono">--checkpoint_path</code></div>
                  </div>
                  <div>
                    <div className="text-xs font-medium text-gray-700 mb-1">Trace path</div>
                    <input
                      value={runOptions.tracePath}
                      onChange={(e) => onRunOptionsChange({ tracePath: e.target.value })}
                      placeholder="e.g. outputs/my_task/trace.jsonl"
                      className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                    />
                    <div className="text-[11px] text-gray-500 mt-1">Maps to <code className="font-mono">--trace_path</code></div>
                  </div>
                  <div>
                    <div className="text-xs font-medium text-gray-700 mb-1">Replay trace</div>
                    <input
                      value={runOptions.replayTrace}
                      onChange={(e) => onRunOptionsChange({ replayTrace: e.target.value })}
                      placeholder="e.g. outputs/my_task/trace.jsonl"
                      className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                    />
                    <div className="text-[11px] text-gray-500 mt-1">
                      Maps to <code className="font-mono">--replay_trace</code> (no real tool calls)
                    </div>
                  </div>
                </div>

                <div>
                  <div className="text-xs font-medium text-gray-700 mb-1">Extra args</div>
                  <input
                    value={runOptions.extraArgs}
                    onChange={(e) => onRunOptionsChange({ extraArgs: e.target.value })}
                    placeholder="e.g. --max_tokens_per_step 20000"
                    title="Tip: include -- to forward args to python (e.g. -- --flag value)"
                    className="w-full px-2 py-1.5 text-sm text-gray-900 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-green-200"
                  />
                  <div className="text-[11px] text-gray-500 mt-1 break-words">
                    Tip: include <code className="font-mono">--</code> to forward args to python
                    (e.g. <code className="font-mono">-- --flag value</code>).
                  </div>
                </div>
              </div>

              <div className="px-3 py-2 border-t border-gray-100 flex justify-end flex-shrink-0">
                <button
                  onClick={() => setShowRunMenu(false)}
                  className="px-2 py-1 text-sm rounded hover:bg-gray-100 text-gray-700"
                >
                  Close
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="w-px h-4 bg-gray-200 mx-1" />

        <div className="relative" ref={importMenuRef}>
          <button
            onClick={() => setShowImportMenu(!showImportMenu)}
            className={`px-2 py-1 rounded-md flex items-center gap-0.5 text-xs ${
              showImportMenu ? 'bg-slate-900 text-white shadow-sm' : 'hover:bg-slate-100 text-gray-700'
            }`}
            title="Import YAML, submodules, or folder"
          >
            <Upload size={14} />
            <span className="hidden sm:inline">Import</span>
            <ChevronDown size={12} className={`transition-transform ${showImportMenu ? 'rotate-180' : ''}`} />
          </button>
          {showImportMenu && (
            <div className="absolute left-0 top-full mt-1 w-56 bg-white rounded-lg shadow-lg border border-gray-200 py-2 z-50">
              <button
                onClick={() => { onImport(); setShowImportMenu(false); }}
                className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gray-100 text-left text-sm text-gray-700"
              >
                <FileText size={18} className="text-gray-500" />
                YAML plan
              </button>
              {onImportSubmodules && (
                <button
                  onClick={() => { onImportSubmodules(); setShowImportMenu(false); }}
                  className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gray-100 text-left text-sm text-gray-700"
                >
                  <Package size={18} className="text-gray-500" />
                  Submodule
                </button>
              )}
              {onImportFolder && (
                <button
                  onClick={() => { onImportFolder(); setShowImportMenu(false); }}
                  className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gray-100 text-left text-sm text-gray-700"
                >
                  <FolderOpen size={18} className="text-gray-500" />
                  Folder
                </button>
              )}
            </div>
          )}
        </div>
        
        <div className="relative" ref={menuRef}>
          <button
            onClick={() => setShowExportMenu(!showExportMenu)}
            className={`px-2 py-1 rounded-md flex items-center gap-0.5 text-xs ${
              showExportMenu
                ? 'bg-slate-900 text-white shadow-sm'
                : 'hover:bg-slate-100 text-gray-700'
            }`}
            title="Export options"
          >
            <Download size={14} />
            <span className="hidden sm:inline">Export</span>
            <ChevronDown size={12} className={`transition-transform ${showExportMenu ? 'rotate-180' : ''}`} />
          </button>

          {showExportMenu && (
            <div className="absolute right-0 top-full mt-1 w-64 bg-white rounded-lg shadow-lg border border-gray-200 py-2 z-50">
              {/* YAML export */}
              <button
                onClick={() => { onExport(); setShowExportMenu(false); }}
                className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gray-100 text-left text-sm text-gray-700"
              >
                <FileText size={18} className="text-gray-500" />
                <span>YAML file</span>
              </button>

              {onExportFolder && (
                <button
                  onClick={() => { onExportFolder(); setShowExportMenu(false); }}
                  className="w-full flex items-center gap-3 px-3 py-2 hover:bg-gray-100 text-left text-sm text-gray-700"
                >
                  <FolderOpen size={18} className="text-gray-500" />
                  <span>Folder (zip)</span>
                </button>
              )}

              <div className="my-2 border-t border-gray-100" />

              {/* Image export header */}
              <div className="px-3 pb-1 flex items-center gap-2">
                <Image size={16} className="text-gray-500" />
                <span className="text-sm font-medium text-gray-800">Image</span>
              </div>

              {/* Image export: resolution selector */}
              <div className="px-3 py-2 border-b border-gray-100">
                <div className="text-xs text-gray-500 mb-2">Resolution (PNG/PDF)</div>
                <div className="flex gap-1">
                  {SCALE_OPTIONS.map((option) => (
                    <button
                      key={option.value}
                      onClick={() => setSelectedScale(option.value)}
                      className={`flex-1 px-2 py-1 text-xs rounded transition-colors ${
                        selectedScale === option.value
                          ? 'bg-blue-500 text-white'
                          : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                      }`}
                      title={option.description}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              </div>

              {/* Image export: format selector */}
              <div className="px-3 py-2">
                <div className="text-xs text-gray-500 mb-2">Format</div>
                <div className="flex gap-2">
                  {formats.map((format) => {
                    const Icon = FORMAT_ICONS[format.value];
                    return (
                      <button
                        key={format.value}
                        onClick={() => handleExportFormat(format.value)}
                        className="flex-1 inline-flex items-center justify-center gap-1 px-2 py-1.5 rounded border border-gray-200 hover:bg-gray-100 text-xs font-medium text-gray-700 transition-colors"
                      >
                        <Icon size={14} className="text-gray-500" />
                        <span>{format.label}</span>
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
        
        <div className="w-px h-4 bg-gray-200 mx-1" />
        
        {/* Undo/Redo buttons */}
        <button
          onClick={onUndo}
          disabled={!canUndo}
          className={`p-1 rounded-md flex items-center ${
            canUndo
              ? 'hover:bg-slate-100 text-gray-700'
              : 'text-gray-300 cursor-not-allowed'
          }`}
          title={`Undo (${isMac ? '⌘' : 'Ctrl'}+Z)`}
        >
          <Undo2 size={14} />
        </button>
        <button
          onClick={onRedo}
          disabled={!canRedo}
          className={`p-1 rounded-md flex items-center ${
            canRedo
              ? 'hover:bg-slate-100 text-gray-700'
              : 'text-gray-300 cursor-not-allowed'
          }`}
          title={`Redo (${isMac ? '⌘' : 'Ctrl'}+Shift+Z)`}
        >
          <Redo2 size={14} />
        </button>
        
        <div className="w-px h-4 bg-gray-200 mx-1" />
        
        {/* Layout split-button: main = auto-layout, dropdown = direction */}
        <div className="relative flex rounded-md bg-white border border-slate-200 shadow-sm" ref={layoutMenuRef}>
          <button
            type="button"
            onClick={onAutoLayout}
            className="px-2 py-1 flex items-center gap-0.5 text-xs hover:bg-slate-100 text-gray-700 rounded-l-md"
            title="Auto layout"
          >
            <LayoutGrid size={14} />
            <span className="hidden sm:inline">Layout</span>
          </button>
          <button
            type="button"
            onClick={() => setShowLayoutMenu(!showLayoutMenu)}
            className={`px-1.5 py-1 border-l border-slate-200 flex items-center rounded-r-md ${
              showLayoutMenu ? 'bg-slate-100 text-slate-900' : 'hover:bg-slate-50 text-gray-600'
            }`}
            title="Layout options"
          >
            <ChevronDown size={12} className={`transition-transform ${showLayoutMenu ? 'rotate-180' : ''}`} />
          </button>

          {showLayoutMenu && (
            <div className="absolute right-0 top-full mt-1 w-52 bg-white rounded-lg shadow-lg border border-gray-200 py-2 z-50">
              <div className="px-3 pb-1 text-[11px] font-semibold text-gray-600 uppercase tracking-wide">
                Direction
              </div>
              <button
                onClick={() => { onLayoutDirectionChange('TB'); setShowLayoutMenu(false); }}
                className="w-full flex items-center justify-between px-3 py-2 hover:bg-gray-100 text-left text-sm text-gray-700"
                title="Top → Bottom"
              >
                <span>Vertical</span>
                {layoutDirection === 'TB' && <span className="text-xs text-gray-500">✓</span>}
              </button>
              <button
                onClick={() => { onLayoutDirectionChange('LR'); setShowLayoutMenu(false); }}
                className="w-full flex items-center justify-between px-3 py-2 hover:bg-gray-100 text-left text-sm text-gray-700"
                title="Left → Right"
              >
                <span>Horizontal</span>
                {layoutDirection === 'LR' && <span className="text-xs text-gray-500">✓</span>}
              </button>
              <div className="border-t border-gray-100 my-1" />
              <div className="px-3 pb-1 text-[11px] font-semibold text-gray-600 uppercase tracking-wide">
                Spacing
              </div>
              <button
                onClick={() => { onLayoutCompactChange(false); setShowLayoutMenu(false); }}
                className="w-full flex items-center justify-between px-3 py-2 hover:bg-gray-100 text-left text-sm text-gray-700"
                title="Normal spacing"
              >
                <span>Normal</span>
                {!layoutCompact && <span className="text-xs text-gray-500">✓</span>}
              </button>
              <button
                onClick={() => { onLayoutCompactChange(true); setShowLayoutMenu(false); }}
                className="w-full flex items-center justify-between px-3 py-2 hover:bg-gray-100 text-left text-sm text-gray-700"
                title="Compact spacing"
              >
                <span>Compact</span>
                {layoutCompact && <span className="text-xs text-gray-500">✓</span>}
              </button>
            </div>
          )}
        </div>
        
        <button
          onClick={onClear}
          className="px-2 py-1 rounded-md hover:bg-red-50 text-red-500 flex items-center gap-0.5 text-xs border border-red-100"
          title="Clear All"
        >
          <Trash2 size={14} />
          <span className="hidden sm:inline">Clear</span>
        </button>
        
        <div className="w-px h-4 bg-gray-200 mx-1" />
        
        <button
          onClick={onToggleYamlEditor}
          className={`px-2 py-1 rounded-md flex items-center gap-0.5 text-xs ${
            showYamlEditor
              ? 'bg-slate-900 text-white shadow-sm'
              : 'hover:bg-slate-100 text-gray-700'
          }`}
          title={showYamlEditor ? 'Show Config Panel' : 'Show YAML Editor'}
        >
          {showYamlEditor ? <Eye size={14} /> : <Code size={14} />}
          <span className="hidden sm:inline">
            {showYamlEditor ? 'Config' : 'YAML'}
          </span>
        </button>

        <div className="w-px h-4 bg-gray-200 mx-1" />

        <a
          href="https://github.com/OptimalScale/AgentSPEX"
          target="_blank"
          rel="noreferrer"
          className="p-1 rounded-md hover:bg-slate-100 text-gray-700"
          title="Open GitHub repository"
          aria-label="Open GitHub repository"
        >
          <Github size={14} />
        </a>
      </div>
    </div>
  );
}
