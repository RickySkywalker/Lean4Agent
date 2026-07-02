import { toPng, toSvg } from 'html-to-image';
import { getNodesBounds, getViewportForBounds } from '@xyflow/react';
import { jsPDF } from 'jspdf';
import { FlowNode } from '../types';

export type ImageFormat = 'png' | 'svg' | 'pdf';

export interface ExportOptions {
  format: ImageFormat;
  scale?: number; // Scale factor for higher resolution, default 2
  backgroundColor?: string;
  fileName?: string;
}

const DEFAULT_OPTIONS: Required<ExportOptions> = {
  format: 'png',
  scale: 2, // Default 2x scale for higher resolution
  backgroundColor: '#ffffff',
  fileName: 'flow-diagram',
};

/**
 * Get ReactFlow viewport element
 */
function getViewportElement(): HTMLElement | null {
  return document.querySelector('.react-flow__viewport') as HTMLElement | null;
}

/**
 * Calculate node bounds and viewport parameters
 */
function calculateBoundsAndViewport(nodes: FlowNode[], padding = 50) {
  const nodesBounds = getNodesBounds(nodes);
  
  // Add padding
  const width = nodesBounds.width + padding * 2;
  const height = nodesBounds.height + padding * 2;
  
  const viewport = getViewportForBounds(
    {
      ...nodesBounds,
      x: nodesBounds.x - padding,
      y: nodesBounds.y - padding,
      width,
      height,
    },
    width,
    height,
    0.5,
    2,
    0
  );

  return { nodesBounds, viewport, width, height };
}

/**
 * Filter out elements that should not be exported (MiniMap, Controls, etc.)
 */
function createNodeFilter() {
  return (node: Node) => {
    if (node instanceof Element) {
      const className = node.getAttribute('class') || '';
      if (
        className.includes('react-flow__minimap') ||
        className.includes('react-flow__controls')
      ) {
        return false;
      }
    }
    return true;
  };
}

/**
 * Export as high-resolution PNG
 * pixelRatio controls pixel density - higher values produce clearer images
 * Output image pixels = width * pixelRatio × height * pixelRatio
 */
async function exportToPng(
  element: HTMLElement,
  width: number,
  height: number,
  viewport: { x: number; y: number; zoom: number },
  options: Required<ExportOptions>
): Promise<string> {
  return toPng(element, {
    backgroundColor: options.backgroundColor,
    width: width,
    height: height,
    pixelRatio: options.scale, // Use pixelRatio for higher pixel density
    style: {
      width: `${width}px`,
      height: `${height}px`,
      transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
      border: 'none',
      outline: 'none',
    },
    filter: createNodeFilter(),
  });
}

/**
 * Export as SVG (vector graphics, infinitely scalable)
 * Manually adds background rectangle to ensure white background
 */
async function exportToSvg(
  element: HTMLElement,
  width: number,
  height: number,
  viewport: { x: number; y: number; zoom: number },
  options: Required<ExportOptions>
): Promise<string> {
  const svgDataUrl = await toSvg(element, {
    backgroundColor: options.backgroundColor,
    width: width,
    height: height,
    style: {
      width: `${width}px`,
      height: `${height}px`,
      transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
      border: 'none',
      outline: 'none',
      fill: 'none',
    },
    filter: createNodeFilter(),
  });

  // Decode data URL to get SVG content
  const svgContent = decodeURIComponent(svgDataUrl.split(',')[1]);
  
  // Insert background rectangle after <svg> tag
  const bgRect = `<rect width="100%" height="100%" fill="${options.backgroundColor}"/>`;
  const modifiedSvg = svgContent.replace(
    /(<svg[^>]*>)/,
    `$1${bgRect}`
  );

  // Re-encode as data URL
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(modifiedSvg)}`;
}

/**
 * Export as PDF
 * Uses high-resolution PNG embedded in PDF for print quality
 */
async function exportToPdf(
  element: HTMLElement,
  width: number,
  height: number,
  viewport: { x: number; y: number; zoom: number },
  options: Required<ExportOptions>
): Promise<void> {
  // Generate high-resolution PNG first
  const pngDataUrl = await toPng(element, {
    backgroundColor: options.backgroundColor,
    width: width,
    height: height,
    pixelRatio: options.scale,
    style: {
      width: `${width}px`,
      height: `${height}px`,
      transform: `translate(${viewport.x}px, ${viewport.y}px) scale(${viewport.zoom})`,
      border: 'none',
      outline: 'none',
    },
    filter: createNodeFilter(),
  });

  // Create PDF
  const orientation = width > height ? 'landscape' : 'portrait';
  const pdf = new jsPDF({
    orientation,
    unit: 'px',
    format: [width, height],
    hotfixes: ['px_scaling'], // Fix pixel scaling issues
  });

  // Add image to PDF
  pdf.addImage(pngDataUrl, 'PNG', 0, 0, width, height);
  
  // Save PDF
  pdf.save(`${options.fileName}.pdf`);
}

/**
 * Trigger file download
 */
function triggerDownload(dataUrl: string, fileName: string) {
  const a = document.createElement('a');
  a.setAttribute('download', fileName);
  a.setAttribute('href', dataUrl);
  a.click();
}

/**
 * Export flow diagram as image
 * Supports PNG (high-res), SVG (vector), and PDF formats
 */
export async function downloadImage(
  nodes: FlowNode[],
  options: Partial<ExportOptions> = {}
): Promise<void> {
  if (nodes.length === 0) {
    console.warn('No nodes to export');
    return;
  }

  const mergedOptions: Required<ExportOptions> = {
    ...DEFAULT_OPTIONS,
    ...options,
  };

  const element = getViewportElement();
  if (!element) {
    console.error('ReactFlow viewport element not found');
    return;
  }

  const { viewport, width, height } = calculateBoundsAndViewport(nodes);

  try {
    switch (mergedOptions.format) {
      case 'png': {
        const dataUrl = await exportToPng(element, width, height, viewport, mergedOptions);
        triggerDownload(dataUrl, `${mergedOptions.fileName}.png`);
        break;
      }
      case 'svg': {
        const dataUrl = await exportToSvg(element, width, height, viewport, mergedOptions);
        triggerDownload(dataUrl, `${mergedOptions.fileName}.svg`);
        break;
      }
      case 'pdf': {
        await exportToPdf(element, width, height, viewport, mergedOptions);
        break;
      }
      default:
        console.error(`Unsupported format: ${mergedOptions.format}`);
    }
  } catch (error) {
    console.error('Failed to export image:', error);
    throw error;
  }
}

/**
 * Get list of supported export formats
 */
export function getSupportedFormats(): { value: ImageFormat; label: string; description: string }[] {
  return [
    { value: 'png', label: 'PNG', description: 'High-res bitmap, great for sharing' },
    { value: 'svg', label: 'SVG', description: 'Vector graphics, infinitely scalable' },
    { value: 'pdf', label: 'PDF', description: 'Document format, ideal for printing' },
  ];
}
