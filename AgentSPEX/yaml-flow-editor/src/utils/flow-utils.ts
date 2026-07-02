import { FlowNodeData } from '../types';

// Helper to recursively update nested data structure
// Returns the updated root data object
export const updateNestedStructure = (
  currentData: any,
  pathParts: string[],
  targetIndex: number,
  newValue: any
): any => {
  if (pathParts.length === 0 || currentData == null) return currentData;

  const [head, ...tail] = pathParts;
  
  // If head is a number AND currentData is an array, we are traversing an array
  if (!isNaN(Number(head)) && Array.isArray(currentData)) {
    const index = Number(head);
    const item = currentData[index];
    const updatedItem = updateNestedStructure(item, tail, targetIndex, newValue);
    const newData = [...currentData];
    newData[index] = updatedItem;
    return newData;
  }
  
  // Map branch names to actual keys
  let realKey = head;
  let isSwitchCase = false;
  
  if (head === 'then') realKey = 'thenSteps';
  else if (head === 'else') realKey = 'elseSteps';
  else if (head === 'loop') realKey = 'loopSteps';
  else if (head === '__default__') realKey = 'defaultSteps';
  else {
    // Check if it's a switch case
    if (currentData.cases && Array.isArray(currentData.cases[head])) {
      isSwitchCase = true;
    }
  }
  
  // If we are at the end of the path (targeting an array)
  if (tail.length === 0) {
    if (isSwitchCase) {
      const newCases = { ...currentData.cases };
      const targetArray = [...(newCases[head] || [])];
      
      if (newValue === null) {
        // Handle deletion
        const newArray = targetArray.filter((_, i) => i !== targetIndex);
        newCases[head] = newArray;
      } else {
        // Handle update
        targetArray[targetIndex] = newValue;
        newCases[head] = targetArray;
      }
      return { ...currentData, cases: newCases };
    } else {
      const targetArray = [...(currentData[realKey] || [])];
      
      if (newValue === null) {
        // Handle deletion
        const newArray = targetArray.filter((_, i) => i !== targetIndex);
        return { ...currentData, [realKey]: newArray };
      } else {
        // Handle update
        targetArray[targetIndex] = newValue;
        return { ...currentData, [realKey]: targetArray };
      }
    }
  }
  
  // Recurse deeper
  if (isSwitchCase) {
     const newCases = { ...currentData.cases };
     const array = newCases[head] || [];
     newCases[head] = updateNestedStructure(array, tail, targetIndex, newValue);
     return { ...currentData, cases: newCases };
  } else {
     const array = currentData[realKey] || [];
     const newArray = updateNestedStructure(array, tail, targetIndex, newValue);
     return { ...currentData, [realKey]: newArray };
  }
};

// Get item at specific path and index
export const getNestedItem = (
  currentData: any,
  pathParts: string[],
  targetIndex: number
): FlowNodeData | null => {
  if (pathParts.length === 0 || currentData == null) return null;

  const [head, ...tail] = pathParts;
  
  if (!isNaN(Number(head)) && Array.isArray(currentData)) {
    const index = Number(head);
    return getNestedItem(currentData[index], tail, targetIndex);
  }
  
  let realKey = head;
  let isSwitchCase = false;
  
  if (head === 'then') realKey = 'thenSteps';
  else if (head === 'else') realKey = 'elseSteps';
  else if (head === 'loop') realKey = 'loopSteps';
  else if (head === '__default__') realKey = 'defaultSteps';
  else {
    if (currentData.cases && Array.isArray(currentData.cases[head])) {
      isSwitchCase = true;
    }
  }
  
  if (tail.length === 0) {
    if (isSwitchCase) {
      return currentData.cases[head]?.[targetIndex] || null;
    } else {
      return currentData[realKey]?.[targetIndex] || null;
    }
  }
  
  if (isSwitchCase) {
     return getNestedItem(currentData.cases[head] || [], tail, targetIndex);
  } else {
     return getNestedItem(currentData[realKey] || [], tail, targetIndex);
  }
};

// Adjust target path if it was affected by source removal
export const adjustTargetPath = (sourceBranch: string, sourceIndex: number, targetBranch: string): string => {
  const sourceParts = sourceBranch.split('.');
  const targetParts = targetBranch.split('.');
  
  // If target path is shorter or equal to source path, it's not a descendant (unless same list, handled elsewhere)
  if (targetParts.length <= sourceParts.length) return targetBranch;
  
  // Check if target is a descendant of the source list
  // i.e. sourcePath prefix matches targetPath prefix
  for (let i = 0; i < sourceParts.length; i++) {
    if (sourceParts[i] !== targetParts[i]) return targetBranch;
  }
  
  // sourceParts points to the list that was modified.
  // targetParts[sourceParts.length] is the index in that list that leads to the target.
  const affectedIndexStr = targetParts[sourceParts.length];
  const affectedIndex = Number(affectedIndexStr);
  
  if (isNaN(affectedIndex)) return targetBranch;
  
  // If the item removed was before the path to the target, shift the index down
  if (sourceIndex < affectedIndex) {
    const newParts = [...targetParts];
    newParts[sourceParts.length] = String(affectedIndex - 1);
    return newParts.join('.');
  }
  
  return targetBranch;
};

// Insert item at specific path and index
export const insertNestedItem = (
  currentData: any,
  pathParts: string[],
  targetIndex: number,
  newItem: FlowNodeData
): any => {
  if (pathParts.length === 0 || currentData == null) return currentData;

  const [head, ...tail] = pathParts;
  
  if (!isNaN(Number(head)) && Array.isArray(currentData)) {
    const index = Number(head);
    const item = currentData[index];
    const updatedItem = insertNestedItem(item, tail, targetIndex, newItem);
    const newData = [...currentData];
    newData[index] = updatedItem;
    return newData;
  }
  
  let realKey = head;
  let isSwitchCase = false;
  
  if (head === 'then') realKey = 'thenSteps';
  else if (head === 'else') realKey = 'elseSteps';
  else if (head === 'loop') realKey = 'loopSteps';
  else if (head === '__default__') realKey = 'defaultSteps';
  else {
    if (currentData.cases && Array.isArray(currentData.cases[head])) {
      isSwitchCase = true;
    }
  }
  
  if (tail.length === 0) {
    if (isSwitchCase) {
      const newCases = { ...currentData.cases };
      const targetArray = [...(newCases[head] || [])];
      targetArray.splice(targetIndex, 0, newItem);
      newCases[head] = targetArray;
      return { ...currentData, cases: newCases };
    } else {
      const targetArray = [...(currentData[realKey] || [])];
      targetArray.splice(targetIndex, 0, newItem);
      return { ...currentData, [realKey]: targetArray };
    }
  }
  
  if (isSwitchCase) {
     const newCases = { ...currentData.cases };
     const array = newCases[head] || [];
     newCases[head] = insertNestedItem(array, tail, targetIndex, newItem);
     return { ...currentData, cases: newCases };
  } else {
     const array = currentData[realKey] || [];
     const newArray = insertNestedItem(array, tail, targetIndex, newItem);
     return { ...currentData, [realKey]: newArray };
  }
};
