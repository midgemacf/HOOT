from pydantic import BaseModel, model_validator, field_validator, Field
from pathlib import Path
from typing import List, Optional, Any, Dict, Union
import yaml
from inflection import underscore
from abc import ABC, abstractmethod

def snake_case(str):
    return underscore(str).replace(' ', '_')

def create_page_link(text: str, path: Path, relative_to: Path=None) -> str:
    """Create a link to another page with relative path"""
    if relative_to:
        try:
            relative_path = Path(path).relative_to(relative_to)
            return f"[{text}]({relative_path})"
        except ValueError:
            # Handle case where paths don't share a common root
            pass
    return f"[{text}]({path})"

def create_heading_link(heading: str) -> str:
    """Create a link to a heading in the same document"""
    # Convert heading to GitHub-style anchor
    anchor = heading.lower().replace(' ', '-')
    return f"[{heading}](#{anchor})"

class Tree(BaseModel, ABC):
    # this is my base, both files and directories are this
    path: Path = None
    name: str = None
    description: Optional[str] = None
    parent: Optional["Nest"] = None

    @property
    def order(self):
        return self.__class__.__name__

    @model_validator(mode='before')
    @classmethod
    def define_path(cls, data: Any):
        path = data.get('path')
        name = data.get('name')
        parent = data.get('parent')
        if path is None:
            if parent is None:
                if name is None:
                    return data
                path = Path.cwd() / snake_case(name)
            else:
                path = parent.path / snake_case(name)
            data['path'] = path
            return data
        if name is None:
            path = Path(path)
            name = path.stem
            data['path'] = path
            data['name'] = name
        return data

    @model_validator(mode='after')
    def add_to_nest(self):
        if self.parent:
            self.parent.add_owl(self)
        return self

    def to_dict(self):
        return dict({'name': self.name, 'description': self.description, 'order': self.order})

    @abstractmethod
    def create(self):
        pass

    @abstractmethod
    def create_back_link(self) -> str:
        """Create a back link to parent directory"""
        pass

class Owl(Tree):
    # this is for files
    feathers: List[str] = Field(default_factory=lambda x: []) # These are the headings in that file

    @field_validator('path', mode='before')
    @classmethod
    def ensure_md_extension(cls, value: Any):
        if value is not None:
            if not isinstance(value, Path):
                value = Path(value)
            if value.suffix != '.md':
                value = value.with_suffix('.md')
        return value

    def to_dict(self):
        if self.feathers:
            owl_dict = super().to_dict()
            owl_dict.update({'feathers': self.feathers})
            return owl_dict
        else:
            return super().to_dict()

    def create_toc(self) -> str:
        """Create table of contents with links to headings"""
        if not self.feathers:
            return ""

        toc = "\n## Table of Contents\n"
        for heading in self.feathers:
            toc += f"- {create_heading_link(heading)}\n"
        return toc

    def create(self):
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open('w') as f:
                f.write(f'# {self.name} \n')
                if self.description:
                    f.write(f'{self.description}\n')

                f.write(self.create_toc())

                sub_headings = [f'## {x}\n' for x in self.feathers]
                f.writelines(sub_headings)

                f.write(self.create_back_link())

    def create_back_link(self) -> str:
        """Create a back link to parent directory"""
        if self.parent:
            return f"\n---\n{create_page_link(f'← Back to {self.parent.name}', Path('./README.md'))}\n"
        return ""

    def __eq__(self, other):
        return isinstance(other, self.__class__) and (self.name == other.name and self.path == other.path)

class Nest(Tree):
    # this one is for directories
    owls: List[Tree] = Field(default_factory=lambda: [])

    @field_validator('path', mode='before')
    @classmethod
    def ensure_path(cls, value: Any):
        if not isinstance(value, Path):
            value = Path(value)
        return value

    def to_dict(self):
        if self.owls:
            nest_dict = super().to_dict()
            nest_dict.update({'owls': [x.to_dict() for x in self.owls]})
            return nest_dict
        else:
            return super().to_dict()

    def add_owl(self, owl: Tree):
        if owl not in self.owls:
            self.owls.append(owl)

    def create_contents_list(self) -> str:
        """Create a list of contents with links"""
        if not self.owls:
            return ""

        contents = "\n## Contents\n"
        for owl in sorted(self.owls, key=lambda x: (x.order, x.name)):
            if isinstance(owl, Owl):
                contents += f"- {create_page_link(owl.name, Path(f'./{owl.path.name}'))}\n"
            else:
                contents += f"- {create_page_link(owl.name, Path(f'./{owl.path.name}/README.md'))}\n"
        return contents

    def create(self):
        self.path.mkdir(exist_ok=True, parents=True)
        readme = self.path.joinpath('README.md')
        if not readme.exists():
            with readme.open('w') as f:
                f.write(f'# {self.name}\n')
                if self.description:
                    f.write(self.description)
                f.write(self.create_contents_list())

                f.write(self.create_back_link())

        for owl in self.owls:
            owl.create()

    def create_back_link(self) -> str:
        """Create a back link to parent directory"""
        if self.parent:
            return f"\n---\n{create_page_link(f'← Back to {self.parent.name}', Path('../README.md'))}\n"
        return ""

def to_yaml(tree: Tree, yaml_path: Path, mode: str='w'):
    yaml_str = yaml.safe_dump(data=tree.to_dict(), sort_keys=False)
    with yaml_path.open(mode) as f:
        f.write(yaml_str)

def grow_tree(config: Dict[str, Union[str, Any]], parent: Optional[Tree]=None):
    order = config.pop('order')
    if order == 'Nest':
        owls = config.pop('owls', [])
        nest = Nest(parent=parent, **config)
        owls = [grow_tree(x, parent=nest) for x in owls]
        nest.owls = owls
        return nest
    elif order == 'Owl':
        try:
            return Owl(parent=parent, **config)
        except Exception as e:
            print(f'error on {config.get("name")}')
            raise e

def from_yaml(yaml_path: Path):
    config = yaml.safe_load(yaml_path.read_text())
    return grow_tree(config)

def initial_structure():
    root = Nest(name='HOOT', description='Home Oversight and Operation Tips')

    pets = Nest(name='Pets', description="Everything for helping with the creatures!", parent=root)

    vet_stuff = Owl(name='Vet Care', description='Contact info for vets and things',
                    feathers=['Emergency Vet', 'Normal Vet', 'Snake Vet'], parent=pets)

    cats = Nest(name='Cats', parent=pets)
    cat_feeding = Owl(name='Feeding', parent=cats, feathers=['Normal Times', 'Technique', 'Brands', 'Kibble'])
    litterboxes = Owl(name='Litter boxes', parent=cats, feathers=['Locations', 'Extra Litter', 'Disposal', 'Brand'])
    cat_emergency_plan = Owl(name='Emergency Plan', parent=cats)

    snake = Nest(name='Snake', parent=pets)
    snake_emergency_plan = Owl(name='Emergency Plan', parent=snake)
    tank_info = Owl(name='Tank Info', parent=snake, feathers=['Common Issues', 'Ideal ranges'])
    snake_feeding = Owl(name='Feeding', parent=snake)

    dog = Nest(name='Dog', parent=pets, description='Crazy dog gets kept at a boarding facility')

    kitchen = Owl(name='Kitchen', parent=root, feathers=['Cabinet map', 'Lights info', 'Dishwasher'])
    # wifi = Owl(name='WiFi', parent=root)
    # trash_schedule = Owl(name='Trash schedule', parent=root)

    to_yaml(root, Path('file_structure.yaml'), mode='w')

if __name__ == '__main__':
    structure = from_yaml(Path('file_structure.yaml'))
    structure.create()