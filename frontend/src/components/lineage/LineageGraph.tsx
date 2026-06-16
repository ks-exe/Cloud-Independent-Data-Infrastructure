import { useEffect, useRef, useCallback } from 'react';
import * as d3 from 'd3';
import { Box } from '@mui/material';
import type { LineageGraphNode, LineageGraphEdge } from '../../services/lineage';

interface D3Node extends d3.SimulationNodeDatum {
  id: string;
  name: string;
  type: 'table' | 'system' | 'transformation';
  system: string | null;
  table_name: string | null;
}

interface D3Link extends d3.SimulationLinkDatum<D3Node> {
  source_id: string;
  target_id: string;
  pipeline_name: string | null;
}

interface LineageGraphProps {
  nodes: LineageGraphNode[];
  edges: LineageGraphEdge[];
  onNodeSelect: (nodeId: string) => void;
  selectedNodeId: string | null;
}

/** Color map for node types */
const NODE_COLORS: Record<string, string> = {
  system: '#4caf50',        // green for sources
  table: '#2196f3',         // blue for tables
  transformation: '#ff9800', // orange for transformations
};

/**
 * D3.js force-directed graph component for lineage visualization.
 * Supports zoom/pan, directional arrows on edges, tooltips on hover, and node selection.
 */
export default function LineageGraph({
  nodes,
  edges,
  onNodeSelect,
  selectedNodeId,
}: LineageGraphProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement | null>(null);
  const simulationRef = useRef<d3.Simulation<D3Node, D3Link> | null>(null);

  const renderGraph = useCallback(() => {
    if (!containerRef.current || nodes.length === 0) return;

    // Clean up previous render
    d3.select(containerRef.current).selectAll('svg').remove();

    const width = containerRef.current.clientWidth;
    const height = containerRef.current.clientHeight || 500;

    // Create SVG
    const svg = d3
      .select(containerRef.current)
      .append('svg')
      .attr('width', width)
      .attr('height', height)
      .attr('viewBox', `0 0 ${width} ${height}`)
      .style('background', '#fafafa')
      .style('border-radius', '8px');

    svgRef.current = svg.node();

    // Define arrow markers for directed edges
    svg
      .append('defs')
      .append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '-0 -5 10 10')
      .attr('refX', 28)
      .attr('refY', 0)
      .attr('orient', 'auto')
      .attr('markerWidth', 8)
      .attr('markerHeight', 8)
      .append('path')
      .attr('d', 'M 0,-5 L 10,0 L 0,5')
      .attr('fill', '#999');

    // Create zoom behavior
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 4])
      .on('zoom', (event) => {
        g.attr('transform', event.transform);
      });

    svg.call(zoom);

    // Container group for zoom/pan
    const g = svg.append('g');

    // Tooltip div
    const tooltip = d3
      .select(containerRef.current)
      .append('div')
      .attr('class', 'lineage-tooltip')
      .style('position', 'absolute')
      .style('visibility', 'hidden')
      .style('background', 'rgba(0,0,0,0.8)')
      .style('color', '#fff')
      .style('padding', '6px 10px')
      .style('border-radius', '4px')
      .style('font-size', '12px')
      .style('pointer-events', 'none')
      .style('z-index', '10');

    // Prepare data
    const d3Nodes: D3Node[] = nodes.map((n) => ({
      id: n.id,
      name: n.name,
      type: n.type,
      system: n.system,
      table_name: n.table_name,
    }));

    const nodeMap = new Map(d3Nodes.map((n) => [n.id, n]));

    const d3Links: D3Link[] = edges
      .filter((e) => nodeMap.has(e.source_id) && nodeMap.has(e.target_id))
      .map((e) => ({
        source: e.source_id,
        target: e.target_id,
        source_id: e.source_id,
        target_id: e.target_id,
        pipeline_name: e.pipeline_name,
      }));

    // Create force simulation
    const simulation = d3
      .forceSimulation<D3Node>(d3Nodes)
      .force(
        'link',
        d3.forceLink<D3Node, D3Link>(d3Links)
          .id((d) => d.id)
          .distance(140)
      )
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collision', d3.forceCollide().radius(40));

    simulationRef.current = simulation;

    // Draw edges
    const link = g
      .append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(d3Links)
      .join('line')
      .attr('stroke', '#999')
      .attr('stroke-opacity', 0.6)
      .attr('stroke-width', 2)
      .attr('marker-end', 'url(#arrowhead)');

    // Draw nodes
    const node = g
      .append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(d3Nodes)
      .join('g')
      .attr('cursor', 'pointer')
      .call(
        d3.drag<SVGGElement, D3Node>()
          .on('start', (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    // Node circles
    node
      .append('circle')
      .attr('r', 18)
      .attr('fill', (d) => NODE_COLORS[d.type] || '#9e9e9e')
      .attr('stroke', (d) =>
        d.id === selectedNodeId ? '#1a237e' : '#fff'
      )
      .attr('stroke-width', (d) => (d.id === selectedNodeId ? 3 : 2));

    // Node labels
    node
      .append('text')
      .text((d) => d.name.length > 14 ? d.name.slice(0, 12) + '…' : d.name)
      .attr('text-anchor', 'middle')
      .attr('dy', 32)
      .attr('font-size', '11px')
      .attr('fill', '#333');

    // Hover tooltip
    node
      .on('mouseover', (event, d) => {
        tooltip
          .style('visibility', 'visible')
          .html(
            `<strong>${d.name}</strong><br/>Type: ${d.type}${d.system ? `<br/>System: ${d.system}` : ''}`
          );
      })
      .on('mousemove', (event) => {
        const containerRect = containerRef.current!.getBoundingClientRect();
        tooltip
          .style('top', `${event.clientY - containerRect.top - 40}px`)
          .style('left', `${event.clientX - containerRect.left + 10}px`);
      })
      .on('mouseout', () => {
        tooltip.style('visibility', 'hidden');
      });

    // Node click for selection
    node.on('click', (_event, d) => {
      onNodeSelect(d.id);
    });

    // Simulation tick
    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as D3Node).x!)
        .attr('y1', (d) => (d.source as D3Node).y!)
        .attr('x2', (d) => (d.target as D3Node).x!)
        .attr('y2', (d) => (d.target as D3Node).y!);

      node.attr('transform', (d) => `translate(${d.x},${d.y})`);
    });

    // Cleanup function
    return () => {
      simulation.stop();
      tooltip.remove();
    };
  }, [nodes, edges, onNodeSelect, selectedNodeId]);

  useEffect(() => {
    const cleanup = renderGraph();
    return () => {
      cleanup?.();
    };
  }, [renderGraph]);

  // Handle resize
  useEffect(() => {
    const handleResize = () => {
      if (simulationRef.current) {
        simulationRef.current.stop();
      }
      renderGraph();
    };

    window.addEventListener('resize', handleResize);
    return () => window.removeEventListener('resize', handleResize);
  }, [renderGraph]);

  return (
    <Box
      ref={containerRef}
      sx={{
        width: '100%',
        height: '100%',
        minHeight: 500,
        position: 'relative',
        overflow: 'hidden',
        borderRadius: 2,
        border: '1px solid',
        borderColor: 'divider',
      }}
    />
  );
}
